# 재현 빌드 설계

## 프로젝트 영역

| 영역 | 내용 | 빌드 사용 |
|---|---|---|
| `analysis/` | 사람이 기록한 분석 근거와 검토 기록 | 근거 확인 |
| `source/` | 리터럴 바이트·토큰·주소·텍스트 원천표, 로고 PNG와 `source-map.csv` 빌드 설정 | 사용 |
| 결과 대조 영역 | 완료본·IPS·추출 이미지 | 결과 대조 |

## 처리 흐름

원본 D88/ROM을 검사하고, 분석 근거와 원본 바이트를 대조한 뒤, 검토된 원천표를 직접 기록기에 전달합니다. 로고 설정표는 PNG별 이미지와 source 영역을 정의하며, PNG 여섯 장은 매번 같은 길이의 게임 source stream으로 인코딩됩니다. 기록기는 raw 표 또는 RAM-to-raw 대응표를 통해 원본 복사본에 적용하고 결과를 다시 파싱·검증합니다.

## 원천 행의 계약

리터럴 변경 행은 컴포넌트, 실행 주소 또는 물리 위치, 이전 값, 새 값, 길이, 근거 위치, 검토 상태를 가져야 합니다. 로고는 `source-map.csv`에서 이미지 경로, 그룹, plane, RAM base, 길이, 해상도, 인코더, 기준 픽셀 해시를 명시합니다. 이전 값 누락, 중복 오프셋, 모호한 주소, 추정 토큰, PNG와 설정의 메타데이터 불일치는 빌드 오류입니다.

## 명령

```text
python -m tools.valis_rebuild source-lint
python -m tools.valis_rebuild text-lint
python -m tools.valis_rebuild build --d88 import --rom import
python -m tools.valis_rebuild verify --d88 output --rom output
```

비교 명령으로 결과를 기준 파일과 대조합니다.
