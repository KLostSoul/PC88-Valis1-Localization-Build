# 직접 바이너리 재현 빌드 안내서

## 1. 이 프로젝트의 방식

디버거로 원본 프로그램을 역어셈블하고 실행 경로를 확인한 뒤, 실제 수정 위치를 확정하여 Python이 원본 복사본에 리터럴 바이트를 직접 기록합니다.

분석은 `QUASI88 0.7.4`의 디버그 기능을 이용했습니다.

따라서 다음 세 가지를 구분합니다.

1. 분석 근거: 디버거 주소, 역어셈블 명령, 메모리/섹터 관계, 제어 토큰 판정
2. 빌드 소스: 사람이 확정한 원본 바이트·변경 바이트·주소·길이·문자/번역 행
3. 비교 결과: 완료본 ZIP이나 완료 패치롬과의 로컬 바이트 비교

확정된 소스 행이 빌드에 참여합니다.

## 2. 입력과 출력

### 사용자가 로컬에서 제공하는 입력

- 원본 PC-88 D88 디스크 이미지
- 원본 `KANJI1.ROM`

원본 D88은 `source/media/d88-layout.json`, 원본 `KANJI1.ROM`은 `source/media/kanji1-layout.json`의 레이아웃을 기준으로 확인합니다.

두 파일은 해시와 크기를 먼저 확인합니다. 원본 바이트 가드가 맞지 않으면 해당 위치의 수정은 중단됩니다. 이 검사는 다른 버전의 롬에 조용히 패치를 적용하는 일을 막습니다.

### 빌드가 만드는 출력

- 재조립된 D88
- 재생성된 KANJI1 ROM
- 단계별 검증 로그와 구조 보고서

출력은 `build/` 아래에만 만들며 Git에 커밋하지 않습니다.

## 3. 확정 소스의 구성

| 영역 | 확정 소스 | 역할 |
|---|---|---|
| 이벤트 블록 1~6 | `source/tables/events/`, `source/text/` | 원문·한글 번역과 최종 raw 바이트 |
| 게임오버 | `gameover-fixed.jsonl`, `gameover-scroll.jsonl`, `gameover/hold-34-35.json` | 고정 15개와 스크롤 35개의 행·토큰·보류 영역 |
| 엔딩 | `tables/ending/`, `text/ending-24.jsonl` | 24개 세그먼트, 종결자, 길이와 물리 위치 |
| 로고 | `tables/logo/`, `tables/logo/edit_layers/` | RAM 관찰값·PNG plane·최종 raw 기록의 대응 |
| ERROR 07 | `tables/error07/` | 최종 명령 스트림 바이트와 입력 근거 |
| 문자·칸지 | `source/tables/kanji/`, `source/kanji/` | 476개 글리프와 슬롯·토큰·ROM 오프셋 |
| 제어 토큰 | `tables/tokens/` | 제어 바이트와 일반 문자 바이트의 구분 |
| 역어셈 관찰 | `source/asm/` | 수정 이유와 실행 위치를 설명하는 참고 기록 |

최종 원시 변경표 자체가 각 컴포넌트의 폐쇄된 원본→결과 계약입니다. 별도의 사후 통합 덮어쓰기 표는 두지 않습니다.

## 4. 단계별 명령

### 소스 상태 확인

```sh
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
```

`source-lint`는 확정 목록의 파일 존재 여부, 해시 계약, 표의 기본 형식을 확인합니다. `text-lint`는 원문·번역문·한국어 검증 행과 게임오버 15/35, 엔딩 24의 번호 체계를 확인합니다. 두 명령 모두 문서를 읽어 새 소스를 만들지 않습니다.

### 원본 구조 내보내기

```sh
PYTHONPATH=. python -m tools.valis_rebuild export-original \
  --d88 /path/to/original.d88 \
  --out build/export-original
```

이 단계는 트랙·섹터·payload 구조를 보고합니다.

### 컴포넌트별 빌드

```sh
PYTHONPATH=. python -m tools.valis_rebuild build-d88 \
  --d88 /path/to/original.d88 \
  --out build/reproduction/d88

PYTHONPATH=. python -m tools.valis_rebuild build-rom \
  --rom /path/to/KANJI1.ROM \
  --out build/reproduction/kanji
```

### 통합 빌드

```sh
PYTHONPATH=. python -m tools.valis_rebuild build \
  --d88 /path/to/original.d88 \
  --rom /path/to/KANJI1.ROM \
  --out build/reproduction
```

### 검증

```sh
PYTHONPATH=. python -m tools.valis_rebuild verify \
  --d88 "build/reproduction/d88/valis_disk_a(K).d88" \
  --rom "build/reproduction/kanji/KANJI1(K).ROM"

PYTHONPATH=. python -m unittest discover -s tests -v
```

동일 입력으로 두 번 만든 출력의 SHA-256이 같은지 확인해야 재현성이 성립합니다. 완료본과의 바이트 비교는 마지막 진단 단계이며, 비교 결과가 소스 데이터를 갱신하지 않습니다.

## 5. 직접 바이트 기록

역어셈블·디버거 확인으로 확정한 바이너리 위치에 직접 바이트를 기록합니다. ASM 자료는 관찰 주소와 명령을 확인하는 데 사용합니다.
