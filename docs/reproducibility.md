# 재현 빌드 검증 절차

## 목적

이 절차는 원본 D88/ROM과 확정 소스로 같은 결과를 다시 만들 수 있는지 확인합니다.

## 실행 순서

```sh
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
PYTHONPATH=. python -m unittest discover -s tests -v
```

그 다음 사용자가 보유한 원본을 지정합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild build \
  --d88 /path/to/original.d88 \
  --rom /path/to/KANJI1.ROM \
  --out build/reproduction
```

출력 검증은 다음과 같습니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild verify \
  --d88 "build/reproduction/d88/valis_disk_a(K).d88" \
  --rom "build/reproduction/kanji/KANJI1(K).ROM"
```

동일 명령을 별도 출력 디렉터리에 한 번 더 실행하고 두 결과의 SHA-256을 비교합니다. 결과를 기준 파일과 대조할 때는 다음 명령을 사용합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild compare \
  --built "build/reproduction/d88/valis_disk_a(K).d88" \
  --reference /path/to/reference.d88 \
  --fail-on-diff
```

## 검증 단계의 의미

| 단계 | 확인 내용 | 소스 변경 여부 |
|---|---|---|
| `source-lint` | 확정 표·경로·해시 계약, 로고 source-map 설정과 PNG 형식·크기·기준 픽셀 해시 | 없음 |
| `text-lint` | 원문·번역·토큰·번호 체계 | 없음 |
| `export-original` | 원본 D88 트랙·섹터·payload 구조 | 없음 |
| `build-d88` | 원본 가드, 직접 raw 기록, 편집 로고의 source 재인코딩 | 출력 생성 |
| `build-rom` | 476개 글리프와 ROM 오프셋 | 출력 생성 |
| `verify` | 결과 구조·크기·해시·재파싱 | 없음 |
| `compare` | 기준 파일과 결과의 차이 | 없음 |

불일치가 나오면 소스 행과 분석 근거를 다시 검토합니다.
