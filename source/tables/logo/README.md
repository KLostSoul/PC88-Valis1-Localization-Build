# 타이틀 로고 입력과 빌드

## 실제 이미지 입력

로고 이미지는 `source/GFX/`의 PNG 6개다. PNG 편집 뒤 경로, 해상도, 위치를 유지하고
흑백 1비트 픽셀로 저장한다. 회색, 안티앨리어싱,
투명 픽셀은 허용하지 않는다.

`source-map.csv`는 빌드가 읽는 로고 설정표이자 이미지 입력과 게임 메모리 영역의
연결 정보다. 각 행은 PNG 경로, 그룹명, plane, RAM 시작 주소, 압축 source 길이,
가로·세로 픽셀, 061F/05CE 인코더, 기준 픽셀 SHA-256을 지정한다. 빌더는 이 표에서
그룹과 영역을 구성하므로 같은 값을 Python 코드에 별도로 하드코딩하지 않는다.
기준 픽셀 해시는 각 PNG의 기준 이미지 여부를 기록한다.

## 빌드 동작

`build-d88`과 통합 `build`는 매번 PNG 여섯 장을 읽어 모든 그룹을 061F 또는 05CE
source stream으로 인코딩한다. 디코딩 roundtrip과 원래 source 영역 길이를 확인한 뒤
`ram-to-raw-map.csv`의 검증된 D88 payload 위치에 기록한다.

| 그룹 | 이미지 | plane | 영역 | 인코더 |
|---|---|---|---|---|
| `valis_logo` | `VALIS_5D_red_body_640x119_EDIT_1x.png`, `VALIS_5E_black_shadow_mask_640x119_EDIT_1x.png` | 5D, 5E | `0x2800`, 6,503 bytes | 061F, 640×119 |
| `mugen_movement` | `MUGEN_MOVEMENT_05CE_columns_520x24_EDIT_1x.png` | column | `0x4167`, 670 bytes | 05CE, 520×24 |
| `mugen_final` | `MUGEN_FINAL_5C_200x24_EDIT_1x.png`, `MUGEN_FINAL_5D_200x24_EDIT_1x.png`, `MUGEN_FINAL_5E_200x24_EDIT_1x.png` | 5C, 5D, 5E | `0x4405`, 990 bytes | 061F, 200×24 |

## 파일 역할

- `source-map.csv`: 빌드 설정과 PNG·plane·RAM source 영역 연결
- `ram-to-raw-map.csv`: source RAM 주소와 D88 payload 간 역매핑 및 원본 바이트 가드
- `valis-call-map.csv`, `mugen-fixed-call-map.csv`, `mugen-movement-call-map.csv`: 인코더 분석 근거이며 런타임 빌드 입력은 아님
- `report.json`: 소스 표·PNG·역매핑 검수 기록
- `source/GFX/*.png`: 저장소에 포함되는 편집 가능 빌드 입력
