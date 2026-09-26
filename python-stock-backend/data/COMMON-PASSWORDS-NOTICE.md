# common-passwords-15plus.txt 출처

- 원본: SecLists `Passwords/Common-Credentials/xato-net-10-million-passwords-1000000.txt`
  - https://github.com/danielmiessler/SecLists/blob/c205c36a445bff37f8e58a9ec829105cd4975c58/Passwords/Common-Credentials/xato-net-10-million-passwords-1000000.txt
  - 커밋 `c205c36a445bff37f8e58a9ec829105cd4975c58`, 원본 100만 줄, SHA-256 앞 16자 `424a3e03a17df0a2`
- 라이선스: MIT(SecLists 저장소 LICENSE). 아래 고지를 함께 둔다.
- 가공(2026-09-26): 줄마다 NFKC 정규화 → 소문자 → 15자 이상 64자 이하만 남김 → 중복 제거 → 정렬. 결과 10,898줄.
  이 서비스의 최소 길이가 15자라 더 짧은 항목은 어차피 길이 검사에서 걸린다.
- 쓰는 곳: `python-stock-backend/passwords.py` `problem()`이 전체 일치만 거절한다(NIST SP 800-63B-4 §3.1.1.2).

```text
MIT License

Copyright (c) 2018 Daniel Miessler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
