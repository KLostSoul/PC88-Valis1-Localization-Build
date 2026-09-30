# 재현 빌드 명세

## 목적

원본 Disk A D88과 원본 KANJI1 ROM을 입력으로 받아 검토된 직접 바이트 표를 적용하고, `source/GFX/`의 로고 PNG는 게임 source 형식으로 인코딩해 D88에 반영합니다. 파일 구조와 최종 해시도 확인합니다.

## 입력과 출력

- 입력: 사용자가 제공한 원본 D88과 KANJI1 ROM
- 출력: 원본 컨테이너를 보존한 재현 D88과 수정된 KANJI1 ROM
- 결과 대조: 완료본·IPS·추출 이미지와 결과를 비교합니다.

원본 D88은 `source/media/d88-layout.json`, 원본 KANJI1 ROM은 `source/media/kanji1-layout.json`의 레이아웃을 기준으로 확인합니다.

## 적용 규칙

1. 원본 파일 크기와 해시를 확인합니다.
2. 모든 직접 수정 행의 old 값이 원본 위치와 일치하는지 확인합니다.
3. 섹터 헤더와 payload가 아닌 영역은 쓰지 않습니다.
4. 중복·겹침·충돌을 거부합니다.
5. 출력 파일을 재파싱하고 컴포넌트별 변경 집합과 최종 해시를 확인합니다.

로고 PNG는 `source/tables/logo/source-map.csv`에 선언된 경로와 크기를 읽고 픽셀 해시를 확인합니다. 이 표가 그룹, plane, RAM base, source 길이, 인코더까지 빌드 설정의 단일 기준입니다. 기준 이미지와 같으면 검토된 raw 변경표를 쓰고, 편집된 그룹은 061F/05CE로 같은 길이에 재인코딩해 `ram-to-raw-map.csv`를 통해 해당 D88 payload 영역만 교체합니다. PNG 이외의 원본·결과 D88과 ROM은 로컬 입력·출력이며 저장소 산출물이 아닙니다.

## 구성

이벤트 1~6, 게임오버, 엔딩 24개 세그먼트, 로고, ERROR 07, 제어 토큰, KANJI1 글리프와 직접 기록기가 각각 명시된 원천표를 사용합니다.

## 명령

```text
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
PYTHONPATH=. python -m tools.valis_rebuild build --d88 import --rom import
PYTHONPATH=. python -m tools.valis_rebuild verify --d88 . --rom .
```
