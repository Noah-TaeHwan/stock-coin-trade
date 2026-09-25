"""PostgreSQL-backed quant data browser and moving-average backtest API."""
import os
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from errors import error_response


quant_bp = Blueprint("quant", __name__, url_prefix="/api/quant")
_engine = None


def _url():
    return os.environ.get(
        "QUANT_DATABASE_URL",
        "postgresql+psycopg://quant:quant@postgres:5432/quant_research",
    )


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(_url(), pool_pre_ping=True, pool_size=3, max_overflow=2)
    return _engine


def _number(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _rows(result):
    return [{key: _number(value) for key, value in row.items()} for row in result.mappings()]


def _solve(matrix, vector):
    """Gaussian elimination for the small normal-equation systems used below."""
    size = len(vector)
    augmented = [list(matrix[index]) + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("팩터 데이터가 서로 너무 유사해 회귀분석을 할 수 없습니다.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            ratio = augmented[row][column]
            augmented[row] = [value - ratio * base for value, base in zip(augmented[row], augmented[column])]
    return [augmented[row][-1] for row in range(size)]


def _regression(rows, factors):
    # OLS: asset excess return = alpha + factor loadings * factor returns.
    x = [[1.0] + [float(row[name]) for name in factors] for row in rows]
    y = [float(row["asset_return"]) - float(row["risk_free"]) for row in rows]
    columns = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(columns)] for i in range(columns)]
    xty = [sum(row[i] * y[index] for index, row in enumerate(x)) for i in range(columns)]
    coefficients = _solve(xtx, xty)
    predicted = [sum(row[index] * coefficients[index] for index in range(columns)) for row in x]
    mean_y = sum(y) / len(y)
    total = sum((value - mean_y) ** 2 for value in y)
    residual = sum((value - predicted[index]) ** 2 for index, value in enumerate(y))
    return {"alpha_daily": coefficients[0], "loadings": dict(zip(factors, coefficients[1:])),
            "r_squared": 1 - residual / total if total else 0.0, "observations": len(rows)}


def _params():
    symbol = request.args.get("symbol", "005930").upper().strip()
    if not symbol or len(symbol) > 20 or not all(char.isalnum() or char in "-_" for char in symbol):
        raise ValueError("유효한 symbol을 입력하세요.")
    limit = max(1, min(int(request.args.get("limit", 100)), 500))
    return symbol, limit


@quant_bp.get("/overview")
def overview():
    try:
        with _db().connect() as conn:
            result = conn.execute(text("""
                SELECT (SELECT count(*) FROM market_data) AS market_rows,
                       (SELECT count(*) FROM strategies) AS strategy_count,
                       (SELECT count(*) FROM trade_logs) AS trade_count,
                       (SELECT array_agg(symbol ORDER BY symbol) FROM (SELECT DISTINCT symbol FROM market_data) s) AS symbols
            """))
            row = _rows(result)[0]
        return jsonify(row)
    except SQLAlchemyError as exc:
        return jsonify({"message": f"퀀트 PostgreSQL에 연결할 수 없습니다: {exc.__class__.__name__}"}), 503


@quant_bp.get("/market-data")
def market_data():
    try:
        symbol, limit = _params()
        with _db().connect() as conn:
            rows = _rows(conn.execute(text("""
                SELECT symbol, trade_time, open, high, low, close, volume, adjusted_close
                FROM market_data WHERE symbol = :symbol
                ORDER BY trade_time DESC LIMIT :limit
            """), {"symbol": symbol, "limit": limit}))
        return jsonify({"rows": rows, "source": "PostgreSQL market_data"})
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except SQLAlchemyError as exc:
        return jsonify({"message": f"데이터 조회 실패: {exc.__class__.__name__}"}), 503


@quant_bp.get("/signals")
def signals():
    try:
        symbol, limit = _params()
        fast = max(2, min(int(request.args.get("fast", 20)), 100))
        slow = max(fast + 1, min(int(request.args.get("slow", 50)), 250))
        sql = text("""
            WITH ma AS (
                SELECT symbol, trade_time, adjusted_close,
                       avg(adjusted_close) OVER (PARTITION BY symbol ORDER BY trade_time ROWS BETWEEN :fast PRECEDING AND CURRENT ROW) AS fast_ma,
                       avg(adjusted_close) OVER (PARTITION BY symbol ORDER BY trade_time ROWS BETWEEN :slow PRECEDING AND CURRENT ROW) AS slow_ma
                FROM market_data WHERE symbol = :symbol
            ), crossed AS (
                SELECT *, lag(fast_ma > slow_ma) OVER (ORDER BY trade_time) AS prior_above FROM ma
            )
            SELECT symbol, trade_time, adjusted_close, fast_ma, slow_ma,
                   CASE WHEN fast_ma > slow_ma AND coalesce(prior_above, false) = false THEN 'BUY'
                        WHEN fast_ma < slow_ma AND coalesce(prior_above, true) = true THEN 'SELL'
                        ELSE 'HOLD' END AS signal
            FROM crossed ORDER BY trade_time DESC LIMIT :limit
        """)
        with _db().connect() as conn:
            rows = _rows(conn.execute(sql, {"symbol": symbol, "fast": fast - 1, "slow": slow - 1, "limit": limit}))
        return jsonify({"rows": list(reversed(rows)), "fast": fast, "slow": slow})
    except ValueError as exc:
        return error_response("시그널 조회 실패: 요청 값을 확인하세요.", exc, 400, key="message")
    except SQLAlchemyError as exc:
        return error_response("시그널 조회 실패: 데이터베이스 오류", exc, 503, key="message")


_MAX_RANGE_DAYS = 366 * 20


def _backtest_request(data):
    """Validate the POST body. Raises ValueError with a user-facing message."""
    from datetime import date, timedelta

    from quantlab import engine as qengine

    symbol = str(data.get("symbol", "005930")).upper().strip()
    if not symbol or len(symbol) > 20 or not all(char.isalnum() or char in "-_^" for char in symbol):
        raise ValueError("유효한 symbol을 입력하세요.")
    strategy = str(data.get("strategy", "ma2050")).strip().lower()
    fast = int(data["fast"]) if data.get("fast") is not None else None
    slow = int(data["slow"]) if data.get("slow") is not None else None
    # The UI sends rates as fractions (0.00015 = 1.5 bps); the engine takes bps. Rounding keeps
    # 0.00015 * 1e4 from becoming 1.4999999999999998, which would change the receipt id.
    def bps(key, default):
        return round(float(data.get(key, default)) * 1e4, 6)

    costs = qengine.Costs(
        fee_bps=bps("feeRate", 0.00015), slippage_bps=bps("slippage", 0.0005), sell_tax_bps=bps("sellTaxRate", 0.0)
    )
    capital = float(data.get("initialCapital", 10_000_000))
    if not (10_000 <= capital <= 1e12):
        raise ValueError("initialCapital은 10,000 이상 1조 이하여야 합니다.")
    end = date.fromisoformat(data["end"]) if data.get("end") else date.today() + timedelta(days=1)
    start = date.fromisoformat(data["start"]) if data.get("start") else end - timedelta(days=366 * 3)
    if not start < end or (end - start).days > _MAX_RANGE_DAYS:
        raise ValueError("기간(start < end, 최대 20년)을 확인하세요.")
    return symbol, strategy, fast, slow, costs, capital, start, end


def _pct(value, digits=4):
    return round(value * 100, digits) if value is not None else None


def _curve(result):
    equity, bench = result["equity"], result["benchmarkEquity"]
    drawdown = equity / equity.cummax() - 1
    return [
        {"t": ts.date().isoformat(), "equity": round(float(e), 2), "benchmark": round(float(b), 2),
         "drawdown": round(float(d), 6), "position": int(p)}
        for ts, e, b, d, p in zip(equity.index, equity, bench, drawdown, result["position"], strict=True)
    ]


class NotEnoughBars(LookupError):
    """The requested symbol and period have fewer than two stored bars."""


class SourceBlocked(PermissionError):
    """Stored bars come from a source the registry does not allow in this profile."""


def _require_allowed_sources(bars) -> None:
    """Backtests only use bars whose source config/data_sources.toml enables for this profile.

    Ingestion already checks the registry, but market_data can also hold rows loaded
    another way (the SQL seed, a restored dump), so the check also runs where data is served.
    """
    import price_sources
    from marketdata import registry

    reg, profile = registry.load(), price_sources.profile()
    for source_id in sorted({bar.source for bar in bars}):
        try:
            allowed = reg.get(source_id).allowed_in(profile)
        except registry.RegistryError:
            allowed = False
        if not allowed:
            raise SourceBlocked(f"데이터 소스 {source_id!r}는 이 배포({profile})에서 사용할 수 없습니다.")


def execute_backtest(data: dict) -> tuple[dict, bool]:
    """Run and store one backtest; returns (response body, reused).

    Shared by POST /api/quant/backtests and the research agent (deskagent), so
    both produce the same receipts. Raises ValueError/TypeError/KeyError for bad
    input, NotEnoughBars, or SQLAlchemyError.
    """
    import json

    from marketdata import store
    from quantlab.backtest import backtest

    symbol, strategy, fast, slow, costs, capital, start, end = _backtest_request(data)
    with _db().begin() as conn:
        bars = store.load_bars(conn, symbol, start=start, end=end)
        if len(bars) < 2:
            raise NotEnoughBars(f"{symbol}의 {start}~{end} 시세가 부족합니다.")
        _require_allowed_sources(bars)
        result = backtest(bars, strategy, fast, slow, costs, capital)
        receipt, summary, bench = result["receipt"], result["metrics"], result["benchmark"]
        inserted = conn.execute(text("""
            INSERT INTO backtest_runs(receipt_id, engine_version, input_sha256, params, sources, first_bar,
                                      last_bar, bar_count, git_sha, metrics, benchmark)
            VALUES (:id, :engine, :input, CAST(:params AS jsonb), :sources, :first, :last, :count, :git,
                    CAST(:metrics AS jsonb), CAST(:benchmark AS jsonb))
            ON CONFLICT (receipt_id) DO NOTHING RETURNING receipt_id
        """), {"id": receipt["receiptId"], "engine": receipt["engineVersion"], "input": receipt["inputSha256"],
               "params": json.dumps(receipt["params"]), "sources": receipt["sources"],
               "first": receipt["firstBar"], "last": receipt["lastBar"], "count": receipt["barCount"],
               "git": receipt["gitSha"], "metrics": json.dumps(summary),
               "benchmark": json.dumps(bench)}).scalar_one_or_none()
        if inserted is None:
            stored = conn.execute(text(
                "SELECT strategy_id, git_sha, created_at FROM backtest_runs WHERE receipt_id = :id"
            ), {"id": receipt["receiptId"]}).mappings().one()
            strategy_id = stored["strategy_id"]
            receipt = {**receipt, "gitSha": stored["git_sha"], "createdAt": stored["created_at"].isoformat()}
        else:
            strategy_id = conn.execute(text("""
                INSERT INTO strategies(name, parameters) VALUES (:name, CAST(:params AS jsonb))
                RETURNING strategy_id
            """), {"name": f"{result['strategy']['label']} {symbol}"[:100],
                   "params": json.dumps({**receipt["params"], "receiptId": receipt["receiptId"]})}).scalar_one()
            conn.execute(text("UPDATE backtest_runs SET strategy_id = :sid WHERE receipt_id = :id"),
                         {"sid": strategy_id, "id": receipt["receiptId"]})
            slip = costs.slippage_bps * 1e-4
            for trade in result["trades"]:
                reference = trade.price / (1 + slip) if trade.side == "BUY" else trade.price / (1 - slip)
                conn.execute(text("""
                    INSERT INTO trade_logs(strategy_id,symbol,trade_time,side,price,quantity,fee,slippage,pnl)
                    VALUES(:id,:symbol,:time,:side,:price,:quantity,:fee,:slippage,:pnl)
                """), {"id": strategy_id, "symbol": symbol, "time": trade.ts.to_pydatetime(), "side": trade.side,
                       "price": trade.price, "quantity": trade.units, "fee": trade.costs,
                       "slippage": abs(trade.price - reference) * trade.units, "pnl": trade.pnl})
            conn.execute(text("""
                INSERT INTO performance_metrics(strategy_id,start_date,end_date,sharpe_ratio,max_drawdown,
                                                annual_return,total_return,trade_count)
                VALUES(:id,:start,:end,:sharpe,:mdd,:annual,:total,:count)
            """), {"id": strategy_id, "start": receipt["firstBar"], "end": receipt["lastBar"],
                   "sharpe": summary["sharpe"], "mdd": _pct(summary["maxDrawdown"]),
                   "annual": _pct(summary["cagr"]), "total": _pct(summary["totalReturn"]),
                   "count": summary["trades"]})
    body = {
        # Keys the existing UI reads; percentages as before.
        "strategyId": strategy_id,
        "tradeCount": summary["trades"],
        "realizedPnl": round(summary["realizedPnl"], 2),
        "totalReturn": _pct(summary["totalReturn"]),
        "sharpeRatio": round(summary["sharpe"], 4) if summary["sharpe"] is not None else None,
        "maxDrawdown": _pct(summary["maxDrawdown"]),
        "annualReturn": _pct(summary["cagr"]),
        "message": ("같은 입력의 기존 실행을 돌려줍니다." if inserted is None
                    else "백테스트 결과와 거래 로그를 PostgreSQL에 저장했습니다."),
        # quantlab results; ratios are fractions here (0.1 = 10%).
        "receiptId": receipt["receiptId"],
        "receipt": receipt,
        "reused": inserted is None,
        "strategy": result["strategy"],
        "parameters": receipt["params"],
        "metrics": summary,
        "benchmark": bench,
        "equity": _curve(result),
        "trades": [{"t": t.ts.isoformat(), "side": t.side, "price": round(t.price, 4), "units": t.units,
                    "costs": round(t.costs, 4), "pnl": round(t.pnl, 4)} for t in result["trades"]],
        "source": receipt["sources"],
    }
    return body, inserted is None


@quant_bp.post("/backtests")
def run_backtest():
    """Run a quantlab backtest on stored bars and keep one receipted run per input."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "JSON 객체 본문이 필요합니다."}), 400
    try:
        body, reused = execute_backtest(data)
        return jsonify(body), (200 if reused else 201)
    except NotEnoughBars as exc:
        return jsonify({"message": str(exc)}), 404
    except SourceBlocked as exc:
        return jsonify({"message": str(exc)}), 403
    except (ValueError, TypeError, KeyError) as exc:
        return error_response("백테스트 실행 실패: 요청 값을 확인하세요.", exc, 400, key="message")
    except SQLAlchemyError as exc:
        return error_response("백테스트 실행 실패: 데이터베이스 오류", exc, 503, key="message")


def stored_backtest(receipt_id: str) -> dict | None:
    """A stored run by receipt id, or None. Raises ValueError for a malformed id, SQLAlchemyError."""
    receipt_id = receipt_id.lower()
    if len(receipt_id) != 64 or any(char not in "0123456789abcdef" for char in receipt_id):
        raise ValueError("receipt id는 64자리 16진수입니다.")
    with _db().connect() as conn:
        row = conn.execute(text("""
            SELECT receipt_id, strategy_id, engine_version, input_sha256, params, sources, first_bar, last_bar,
                   bar_count, git_sha, metrics, benchmark, created_at
            FROM backtest_runs WHERE receipt_id = :id
        """), {"id": receipt_id}).mappings().first()
    if row is None:
        return None
    return {
        "receiptId": row["receipt_id"],
        "strategyId": row["strategy_id"],
        "receipt": {
            "receiptId": row["receipt_id"], "engineVersion": row["engine_version"], "inputSha256": row["input_sha256"],
            "params": row["params"], "sources": list(row["sources"]), "firstBar": row["first_bar"].isoformat(),
            "lastBar": row["last_bar"].isoformat(), "barCount": row["bar_count"], "gitSha": row["git_sha"],
            "createdAt": row["created_at"].isoformat(),
        },
        "parameters": row["params"],
        "metrics": row["metrics"],
        "benchmark": row["benchmark"],
    }


@quant_bp.get("/backtests/<receipt_id>")
def get_backtest(receipt_id):
    """A stored run by its receipt id (the id a backtest response returned)."""
    try:
        body = stored_backtest(receipt_id)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except SQLAlchemyError as exc:
        return error_response("백테스트 조회 실패: 데이터베이스 오류", exc, 503, key="message")
    if body is None:
        return jsonify({"message": "해당 영수증의 실행이 없습니다."}), 404
    return jsonify(body)


def sources_payload() -> dict:
    """The data source registry as this deployment applies it (config/data_sources.toml)."""
    import price_sources

    profile = price_sources.profile()
    sources = price_sources._registry().sources.values()
    return {"profile": profile, "sources": [
        {"id": s.id, "name": s.name, "kind": s.kind, "status": s.status, "enabled": s.allowed_in(profile),
         "redistribution": s.redistribution, "attribution": s.attribution, "termsUrl": s.terms_url,
         "checkedOn": s.checked_on}
        for s in sorted(sources, key=lambda s: s.id)
    ]}


@quant_bp.get("/sources")
def data_sources():
    return jsonify(sources_payload())


@quant_bp.get("/results")
def results():
    try:
        strategy_id = request.args.get("strategyId", type=int)
        with _db().connect() as conn:
            strategies = _rows(conn.execute(text("""
                SELECT s.strategy_id, s.name, s.parameters, s.created_at, p.total_return, p.annual_return, p.trade_count
                FROM strategies s LEFT JOIN performance_metrics p ON p.strategy_id=s.strategy_id
                ORDER BY s.strategy_id DESC LIMIT 20
            """)))
            trades = _rows(conn.execute(text("""
                SELECT trade_id,strategy_id,symbol,trade_time,side,price,quantity,fee,slippage,pnl
                FROM trade_logs WHERE CAST(:sid AS bigint) IS NULL OR strategy_id = :sid
                ORDER BY trade_id DESC LIMIT 50
            """), {"sid": strategy_id}))
        return jsonify({"strategies": strategies, "trades": trades})
    except SQLAlchemyError as exc:
        return jsonify({"message": f"결과 조회 실패: {exc.__class__.__name__}"}), 503


@quant_bp.get("/factor-analysis")
def factor_analysis():
    """Calculate CAPM alpha/beta and Fama-French-style exposures from daily returns."""
    try:
        symbol, _ = _params()
        with _db().begin() as conn:
            rows = _rows(conn.execute(text("""
                WITH prices AS (
                  SELECT trade_time::date factor_date, adjusted_close,
                         lag(adjusted_close) OVER (ORDER BY trade_time) prior_close
                  FROM market_data WHERE symbol=:symbol
                )
                SELECT p.factor_date, (p.adjusted_close / p.prior_close - 1) AS asset_return,
                       f.risk_free, f.market_excess, f.smb, f.hml, f.rmw, f.cma, f.mom
                FROM prices p JOIN factor_returns f ON f.factor_date=p.factor_date
                WHERE p.prior_close IS NOT NULL ORDER BY p.factor_date
            """), {"symbol": symbol}))
            if len(rows) < 60:
                return jsonify({"message": "팩터 분석에는 최소 60개 이상의 가격 관측치가 필요합니다."}), 400
            capm = _regression(rows, ["market_excess"])
            multi_factors = ["market_excess", "smb", "hml", "rmw", "cma", "mom"]
            multi = _regression(rows, multi_factors)
            start, end = rows[0]["factor_date"], rows[-1]["factor_date"]
            alpha_annual = capm["alpha_daily"] * 252 * 100
            for name, loading in multi["loadings"].items():
                conn.execute(text("""
                    INSERT INTO factor_exposures(symbol,model,factor_name,start_date,end_date,loading,alpha_annual,r_squared,observations)
                    VALUES(:symbol,'FF6',:name,:start,:end,:loading,:alpha,:r2,:count)
                    ON CONFLICT(symbol,model,factor_name,start_date,end_date) DO UPDATE SET
                      loading=EXCLUDED.loading, alpha_annual=EXCLUDED.alpha_annual, r_squared=EXCLUDED.r_squared,
                      observations=EXCLUDED.observations, calculated_at=now()
                """), {"symbol": symbol, "name": name, "start": start, "end": end, "loading": loading,
                       "alpha": alpha_annual, "r2": multi["r_squared"], "count": multi["observations"]})
        labels = {"market_excess": "시장 베타", "smb": "규모(SMB)", "hml": "가치(HML)",
                  "rmw": "수익성(RMW)", "cma": "투자(CMA)", "mom": "모멘텀(MOM)"}
        return jsonify({"symbol": symbol, "period": {"start": start, "end": end},
                        "capm": {"alphaAnnual": round(alpha_annual, 4), "beta": round(capm["loadings"]["market_excess"], 4),
                                 "rSquared": round(capm["r_squared"], 4), "observations": capm["observations"]},
                        "multiFactor": {"rSquared": round(multi["r_squared"], 4), "observations": multi["observations"],
                                        "exposures": [{"name": name, "label": labels[name], "loading": round(value, 4)} for name, value in multi["loadings"].items()]},
                        "source": "learning_sample",
                        "notice": "팩터 수익률은 교육용 샘플입니다. 실제 운용에는 검증된 시장·팩터 데이터로 교체해야 합니다."})
    except ValueError as exc:
        return error_response("팩터 분석 실패: 요청 값을 확인하세요.", exc, 400, key="message")
    except SQLAlchemyError as exc:
        return error_response("팩터 분석 실패: 데이터베이스 오류", exc, 503, key="message")


@quant_bp.get("/data-quality")
def data_quality():
    """Re-run the quality checks on the stored bars of one symbol."""
    from datetime import date, timedelta

    from marketdata import quality, store

    symbol = request.args.get("symbol", "005930").upper().strip()
    try:
        days = max(1, min(int(request.args.get("days", 365)), 3650))
    except ValueError:
        return jsonify({"message": "days must be an integer"}), 400
    start = date.today() - timedelta(days=days)
    try:
        with _db().connect() as conn:
            bars = store.load_bars(conn, symbol, start=start)
            run = conn.execute(text(
                "SELECT run_id, source, status, row_count, checksum, finished_at FROM ingestion_runs "
                "WHERE :symbol = ANY(symbols) ORDER BY run_id DESC LIMIT 1"
            ), {"symbol": symbol}).mappings().first()
    except SQLAlchemyError as exc:
        return error_response("데이터 품질 조회 실패: 데이터베이스 오류", exc, 503, key="message")
    findings = quality.check(bars, as_of=datetime.now(timezone.utc))
    return jsonify({
        "symbol": symbol,
        "bars": len(bars),
        "sources": sorted({bar.source for bar in bars}),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warn"),
        "findings": [f.as_dict() for f in findings],
        "lastIngestion": ({**run, "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None}
                          if run else None),
    })
