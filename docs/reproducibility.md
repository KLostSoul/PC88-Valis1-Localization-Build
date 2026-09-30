# 재현 빌드 검증 절차

## 목적

이 절차는 원본 D88/ROM과 확정 소스로 같은 결과를 다시 만들 수 있는지 확인합니다.

## 실행 순서

```sh
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
PYTHONPATH=. python -m unittest discover -s tests -v
```

빌더는 입력 크기와 SHA-256을 기준 레이아웃과 대조합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild build \
  --d88 import \
  --rom import
```

출력 검증은 다음과 같습니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild verify \
  --d88 output \
  --rom output
```

빌드 결과를 기준 D88과 바이트 단위로 대조합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild compare \
  --built output \
  --reference 결과 \
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
