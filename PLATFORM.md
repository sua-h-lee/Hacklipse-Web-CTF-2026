# Hacklipse 플랫폼 서버

Python 3 가상환경에서 실행합니다.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app issue-code
.venv/bin/python app.py
```

issue-code를 참가자마다 한 번 실행하고 출력된 코드를 개인적으로 전달합니다. 서버는 8000 포트에서 실행됩니다. Lightsail에서는 HTTPS 역방향 프록시 뒤에 두고 외부에서 8000 포트로 직접 접근하지 못하게 설정합니다. HTTPS 운영 시 CTF_HTTPS=1을 지정합니다.

CTF_FLAGS_JSON은 문제 순서대로 서로 다른 실제 정답 문자열 15개를 담은 JSON 배열입니다. 서버 환경에 설정한 뒤 재시작합니다. CTF_CATALOG에는 title, description, points를 가진 객체 15개의 JSON 배열 파일 경로를 지정합니다. 기본 배점은 100점입니다. 데이터와 세션 키는 instance에 보관하며 CTF_DATA로 경로를 지정할 수 있습니다. 기존 익명 풀이 기록은 보존되지만 새 참가 코드와 자동 연결되지 않습니다.

## 실행 서버 연결

실행 서버 URL은 HTTPS를 사용합니다. 같은 호스트의 루프백 연결은 HTTP도 지원합니다. CTF_RUNNER_URL과 CTF_RUNNER_TOKEN을 설정합니다. 플랫폼은 실행 서버에 PUT /environments/{player} 요청을 보내며 Authorization 헤더에 Bearer 토큰을 사용합니다. 본문에는 1부터 15까지의 problem과 ttl_seconds(1800)가 들어갑니다. 실행 서버는 참가자별 단일 슬롯을 원자적으로 교체하고 같은 문제 요청은 기존 환경을 반환해야 합니다. 성공 응답은 브라우저에서 접근할 수 있는 url과 만료 시각 expires(Unix 초)를 담은 JSON 객체입니다. 만료된 환경 삭제와 참가자 간 격리는 실행 서버의 역할입니다. 이 연결이 없어도 로그인, 문제 열람, 채점과 점수 확인을 사용할 수 있습니다.

## 출제 전 테스트

플랫폼에서 CTF_PILOT=1을 지정하면 15문제 모두 HKL{testflag}를 사용합니다. 문제를 열 때 현재 참가자의 환경을 자동 시작하고, 다른 문제를 열면 이전 환경을 교체합니다. 같은 문제의 반복 제출은 한 번만 득점합니다. 랩 서버의 러너와 문제 파일은 별도 비공개 저장소 Hacklipse-CTF-Challenges에서 배포합니다. 실행 서버와 플랫폼에는 같은 CTF_RUNNER_TOKEN을 별도로 설정합니다.

이 러너는 신뢰하는 테스트 텍스트 전용입니다. 실제 워게임 코드는 별도 격리 런타임에서 실행하세요. 본 대회 전에는 테스트 풀이 기록과 분리된 DB를 준비하고 CTF_PILOT를 해제한 뒤 서로 다른 HKL{...} 정답 15개를 설정하세요.
