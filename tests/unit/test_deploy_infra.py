"""Guardrails for the AWS demo files: template security properties, compose overlays, deploy.sh logic.

deploy.sh runs here against stub `aws` and `docker` executables, so its
env-file, health-check and rollback logic is exercised without AWS or Docker.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra" / "cloudformation" / "stockdesk.yaml"


class _CfnLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return {node.tag: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {node.tag: loader.construct_sequence(node, deep=True)}
    return {node.tag: loader.construct_mapping(node, deep=True)}


for _tag in ("!Ref", "!Sub", "!GetAtt", "!Select", "!GetAZs", "!If", "!Equals", "!Base64"):
    _CfnLoader.add_constructor(_tag, _intrinsic)


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(), Loader=_CfnLoader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


def test_only_web_ports_are_open(resources):
    ingress = resources["WebSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert sorted((rule["IpProtocol"], rule["FromPort"]) for rule in ingress) == [
        ("tcp", 80),
        ("tcp", 443),
        ("udp", 443),
    ]


def test_instance_requires_imdsv2_and_encrypts_disks(resources):
    host = resources["Host"]["Properties"]
    assert host["MetadataOptions"] == {
        "HttpEndpoint": "enabled",
        "HttpTokens": "required",
        "HttpPutResponseHopLimit": 1,
    }
    assert host["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] is True
    data = resources["DataVolume"]
    assert data["Properties"]["Encrypted"] is True
    assert data["DeletionPolicy"] == data["UpdateReplacePolicy"] == "Snapshot"


def test_deploy_role_is_limited_to_one_repository_environment(resources):
    statement = resources["DeployRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    condition = statement["Condition"]["StringEquals"]
    assert condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert condition["token.actions.githubusercontent.com:sub"] == {
        "!Sub": "repo:${GitHubRepository}:environment:${GitHubEnvironment}"
    }
    actions = {
        action
        for s in resources["DeployRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        for action in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])
    }
    assert not any(a.startswith(("iam:", "ec2:", "cloudformation:")) or a.endswith("*") for a in actions)


def test_release_bucket_is_private_and_tls_only(resources):
    bucket = resources["ReleaseBucket"]["Properties"]
    assert all(bucket["PublicAccessBlockConfiguration"].values())
    policy = resources["ReleaseBucketTlsOnly"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert policy["Effect"] == "Deny" and policy["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}


class _ComposeLoader(yaml.SafeLoader):
    pass


# Compose's merge tags (!reset, !override) become markers so the overlay's intent can be asserted.
_ComposeLoader.add_constructor("!reset", lambda loader, node: ("!reset", None))
_ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_mapping(node, deep=True))


def _compose(name):
    return yaml.load((ROOT / name).read_text(), Loader=_ComposeLoader)


def test_edge_overlay_hides_nginx_and_pins_caddy():
    edge = _compose("compose.edge.yml")["services"]
    assert edge["frontend"]["ports"] == ("!reset", None)
    assert "real-ip.edge.conf" in " ".join(edge["frontend"]["volumes"])
    assert edge["caddy"]["image"].startswith("caddy:2.") and edge["caddy"]["image"] != "caddy:latest"


def test_aws_overlay_pulls_images_and_ships_every_service_log():
    services = _compose("compose.aws.yml")["services"]
    for name in ("frontend", "init", "python-backend", "worker"):
        assert "${ECR_REGISTRY" in services[name]["image"] and "${IMAGE_TAG" in services[name]["image"]
        assert services[name]["build"] == ("!reset", None)
    assert all(service["logging"]["driver"] == "awslogs" for service in services.values())
    assert set(services) >= {"frontend", "init", "python-backend", "worker", "mariadb", "postgres", "redis", "caddy"}


# ── deploy.sh with stub aws/docker ───────────────────────────────────────────

STUB_AWS = """#!/usr/bin/env bash
case "$1 $2" in
  "ssm get-parameters-by-path")
    printf '%s\\t%s\\n' /stock-coin-trade/prod/secret-key 's3cr3t=with=equals' \\
      /stock-coin-trade/prod/admin-email owner@example.com '/stock-coin-trade/prod/bad name' x ;;
  "ecr get-login-password") echo token ;;
  *) exit 2 ;;
esac
"""

# Records every call; `compose ... exec ... /health` fails while IMAGE_TAG is "bad".
STUB_DOCKER = """#!/usr/bin/env bash
echo "IMAGE_TAG=$IMAGE_TAG $*" >> "$CALLS"
# Like the real CLI, read the piped password (otherwise the writer gets SIGPIPE under pipefail).
if [[ "$*" == *"--password-stdin"* ]]; then cat >/dev/null; fi
if [[ "$*" == *" exec "* && "$IMAGE_TAG" == "bad" ]]; then exit 1; fi
if [[ "$*" == "image prune"* && "${PRUNE_FAILS:-}" == 1 ]]; then exit 1; fi
exit 0
"""


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def run_deploy(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "aws", STUB_AWS)
    _stub(bin_dir, "docker", STUB_DOCKER)
    _stub(bin_dir, "sleep", "#!/usr/bin/env bash\nexit 0\n")  # skip the health-check waits
    state = tmp_path / "state"
    calls = tmp_path / "calls.log"

    def run(release: str, tag: str, **extra_env: str):
        env = {
            **os.environ,
            **extra_env,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "AWS_REGION": "ap-northeast-2",
            "ECR_REGISTRY": "123.dkr.ecr.ap-northeast-2.amazonaws.com",
            "LOG_GROUP": "/stockdesk/app",
            "SITE_ADDRESS": "desk.example.com",
            "STATE_DIR": str(state),
            "CALLS": str(calls),
        }
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "ec2" / "deploy.sh"), f"/releases/{release}", tag],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result, state, calls

    return run


def test_deploy_writes_a_private_env_file_from_parameter_names(run_deploy):
    result, state, calls = run_deploy("r1", "good")
    assert result.returncode == 0, result.stderr
    env_file = state / "app.env"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    assert env_file.read_text().splitlines() == ["SECRET_KEY=s3cr3t=with=equals", "ADMIN_EMAIL=owner@example.com"]
    assert "invalid name" in result.stderr
    assert (state / "current").read_text().splitlines() == ["/releases/r1", "good"]
    log = calls.read_text()
    assert "--profile local-db" in log and "-f /releases/r1/compose.aws.yml" in log


def test_unhealthy_release_rolls_back_to_the_recorded_one(run_deploy):
    run_deploy("r1", "good")
    result, state, calls = run_deploy("r2", "bad")
    assert result.returncode == 1 and "rolling back to good" in result.stderr
    assert (state / "current").read_text().splitlines() == ["/releases/r1", "good"]
    last_up = [line for line in calls.read_text().splitlines() if " up -d" in line][-1]
    assert last_up.startswith("IMAGE_TAG=good") and "/releases/r1/" in last_up


def test_healthy_deploy_removes_images_no_container_uses(run_deploy):
    result, _, calls = run_deploy("r1", "good")
    assert result.returncode == 0, result.stderr
    lines = calls.read_text().splitlines()
    prune = [i for i, line in enumerate(lines) if line.endswith("image prune -af")]
    last_up = max(i for i, line in enumerate(lines) if " up -d" in line)
    assert len(prune) == 1 and prune[0] > last_up


def test_rolled_back_deploy_keeps_every_image(run_deploy):
    run_deploy("r1", "good")
    result, _, calls = run_deploy("r2", "bad")
    assert result.returncode == 1
    # r1의 정상 배포에서 한 번만 정리했다. 롤백한 r2는 이미지를 지우지 않는다.
    assert sum(line.endswith("image prune -af") for line in calls.read_text().splitlines()) == 1


def test_failed_image_prune_does_not_fail_a_healthy_deploy(run_deploy):
    result, state, _ = run_deploy("r1", "good", PRUNE_FAILS="1")
    assert result.returncode == 0 and "image prune failed" in result.stderr
    assert (state / "current").read_text().splitlines() == ["/releases/r1", "good"]


def test_first_release_that_fails_does_not_invent_a_rollback(run_deploy):
    result, state, _ = run_deploy("r1", "bad")
    assert result.returncode == 1 and "rolling back" not in result.stderr
    assert not (state / "current").exists()


# ── backup-db.sh with stub aws/docker ────────────────────────────────────────

# `docker exec` on the MariaDB container fails when DUMP_FAILS is set; aws records its calls.
STUB_BACKUP_DOCKER = """#!/usr/bin/env bash
case "$1" in
  ps) [[ "$*" == *service=mariadb* ]] && echo maria-id || echo pg-id ;;
  exec) if [[ -n "${DUMP_FAILS:-}" && "$*" == *maria-id*mariadb-dump* ]]; then exit 1; fi
        cat >/dev/null; echo "t 1" ;;
esac
"""
STUB_BACKUP_AWS = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
"""


@pytest.mark.parametrize("dump_fails", [False, True])
def test_backup_uploads_only_after_every_dump_succeeded(tmp_path, dump_fails):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "docker", STUB_BACKUP_DOCKER)
    _stub(bin_dir, "aws", STUB_BACKUP_AWS)
    calls = tmp_path / "calls.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AWS_REGION": "ap-northeast-2",
        "CALLS": str(calls),
        **({"DUMP_FAILS": "1"} if dump_fails else {}),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "ec2" / "backup-db.sh"), "demo-bucket"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if dump_fails:
        assert result.returncode != 0 and not calls.exists()
    else:
        assert result.returncode == 0, result.stderr
        uploads = calls.read_text().splitlines()
        assert [line.split("/")[-1] for line in uploads] == [
            "mariadb-mockinv.sql.gz",
            "postgres-quant.dump",
            "counts.tsv",
        ]
        assert all("s3://demo-bucket/backups/" in line for line in uploads)


# ── compare_counts (db-counts.sh): restored row counts against counts.tsv ─────


@pytest.mark.parametrize(
    ("restored", "manifest", "ok"),
    [
        ("a 5\nb 0\n", "a 5 5\nb 0 0\n", True),  # unchanged tables restored exactly
        ("a 0\n", "a 5 5\n", False),  # empty restore of an unchanged table
        ("a 6\n", "a 5 7\n", True),  # changed during the dump: anything between before and after
        ("a 4\n", "a 7 5\n", False),  # outside the range, also when the table shrank (bots sell out)
        ("a 5\n", "a 5 5\nb 3 3\n", False),  # table missing from the restore
        ("a 5\nx 1\n", "a 5 5\n", False),  # table the backup did not have
    ],
)
def test_restored_counts_must_match_the_backup_manifest(tmp_path, restored, manifest, ok):
    (tmp_path / "restored").write_text(restored)
    (tmp_path / "counts.tsv").write_text(manifest)
    result = subprocess.run(
        ["bash", "-c", f'source "{ROOT}/scripts/ec2/db-counts.sh"; compare_counts restored counts.tsv'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is ok, result.stdout


# ── Stack updates must not replace the host; the monitor is least-privilege ──


def test_template_is_ascii_only():
    # CloudFormation stored the old template with every non-ASCII character as "??".
    assert TEMPLATE.read_bytes().isascii()


def test_ami_is_pinned_so_a_stack_update_cannot_replace_the_host(template):
    ami = template["Parameters"]["AmiId"]
    assert ami["Type"] == "AWS::EC2::Image::Id" and "Default" not in ami


def test_backups_are_gone_within_the_35_days_the_privacy_policy_promises(resources):
    rules = {r["Id"]: r for r in resources["ReleaseBucket"]["Properties"]["LifecycleConfiguration"]["Rules"]}
    # S3 rounds each step up to the next UTC midnight: 25 + 1 + 7 + 1 = 34 days at worst.
    current = rules["expire-backups"]["ExpirationInDays"]
    noncurrent = rules["old-versions"]["NoncurrentVersionExpiration"]["NoncurrentDays"]
    assert current + noncurrent <= 32


def test_site_address_has_no_default(template):
    assert "Default" not in template["Parameters"]["SiteAddress"]


def test_monitor_code_compiles_and_names_its_handler(resources):
    code = resources["MonitorFunction"]["Properties"]["Code"]["ZipFile"]
    compile(code, "index.py", "exec")
    assert resources["MonitorFunction"]["Properties"]["Handler"] == "index.handler"
    assert "ReservedConcurrentExecutions" not in resources["MonitorFunction"]["Properties"]


def test_monitor_role_can_only_list_backups_and_write_its_own_metrics(resources):
    statements = resources["MonitorRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    actions = {a for st in statements for a in ([st["Action"]] if isinstance(st["Action"], str) else st["Action"])}
    assert "s3:GetObject" not in actions and not any(a.endswith("*") for a in actions)
    by_action = {(st["Action"] if isinstance(st["Action"], str) else st["Action"][0]): st for st in statements}
    assert by_action["cloudwatch:PutMetricData"]["Condition"] == {"StringEquals": {"cloudwatch:namespace": "Stockdesk"}}
    assert by_action["s3:ListBucket"]["Condition"] == {"StringLike": {"s3:prefix": "backups/*"}}


def test_alarms_mail_on_alarm_and_recovery_and_treat_silence_as_failure(resources):
    for name in ("SiteDownAlarm", "BackupStaleAlarm"):
        alarm = resources[name]["Properties"]
        assert alarm["AlarmActions"] == alarm["OKActions"] == [{"!Ref": "AlertTopic"}]
        assert alarm["TreatMissingData"] == "breaching" and alarm["Namespace"] == "Stockdesk"
