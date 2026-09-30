# PC-88 몽환전사 바리스 1 한글패치 빌드
<p align="center">
  <img src="image/Mugen_Senshi_Valis_Disk_A(K)0000.png">

</p>
이 빌드는 PC-88판 《몽환전사 바리스 1》의 원본 이미지를 한글 패치로 적용하는 Python 기반 빌드입니다.

이 빌드는 사용자가 제공한 원본 D88과 `KANJI1.ROM`을 읽고, 검토된 원천 자료를 원본 이미지에 적용합니다. 타이틀 로고는 `source/GFX/`의 PNG를 실제 입력으로 읽어 PC-88 061F/05CE 형식으로 재인코딩하고, 나머지 직접 패치 영역은 확정 바이트 표를 사용합니다. 디스크 섹터의 payload만 수정합니다.

분석한 원본 이미지의 정보는 `source/media/d88-layout.json`, `KANJI1.ROM`은 `source/media/kanji1-layout.json`의 레이아웃을 확인하세요.

## 빌드 구성

- `analysis/`: 분석 근거 장부와 디버거 관찰 자료
- `source/`: 원문·한글 번역·제어 토큰·직접 바이트·로고 PNG 및 로고 빌드 설정·KANJI1 글리프 원천표
- `tools/valis_rebuild/`: D88 처리기, 원본 바이트 검사기, 매니페스트 기반 로고 PNG 인코더, 직접 기록기, ROM 생성기
- `tests/`: 소스·구조·직렬화·통합 검증
- `docs/`: 작업 문서

## 빌드 원칙

```text
분석 근거와 디버거 확인
        ↓ 수동 검토
확정된 원문·한글 번역·토큰·직접 바이트 표·로고 PNG와 source-map 설정
        ↓ 원본 바이트 대조와 편집 로고 재인코딩
원본 D88/ROM 복사본에 기록
        ↓ 구조·해시·테스트 검증
재현된 D88/ROM
```

## 실행

저장소 루트에서 실행합니다.

```console
python -m tools.valis_rebuild source-lint
python -m tools.valis_rebuild text-lint
python -m unittest discover -s tests -v
```

입력은 레이아웃에 기록된 크기와 SHA-256으로 검증합니다.

```console
python -m tools.valis_rebuild build --d88 import --rom import
```

로고를 바꾸려면 `source/GFX/`의 해당 PNG를 흑백 픽셀로 편집한 뒤 같은 빌드 명령을 실행합니다. 빌더는 `source/tables/logo/source-map.csv`에서 이미지 경로, 그룹, plane, RAM 주소·길이, 해상도, 인코더를 읽습니다. 픽셀 변경이 있는 그룹만 재인코딩합니다. 로고별 파일 역할과 영역은 [`source/tables/logo/README.md`](source/tables/logo/README.md)를 참고하세요.

원본 KANJI1 ROM이 들어 있는 `import/` 폴더를 지정해 글리프 ROM만 만들 수도 있습니다.

```console
python -m tools.valis_rebuild build-rom --rom import
```

KANJI1 ROM에 476개 글리프를 적용합니다.

출력을 검증합니다.

```console
python -m tools.valis_rebuild verify --d88 output --rom output
```

결과를 기준 파일과 대조합니다.

```console
python -m tools.valis_rebuild compare --built output --reference 결과 --fail-on-diff
```

결과 D88과 KANJI1 ROM은 `output/`에 생성됩니다.

## 문서

- [빌드 전수 검수](docs/build-audit.md)
- [직접 바이너리 재현 빌드 안내서](docs/direct-binary-build.md)
- [분석 근거와 빌드 소스 대응표](docs/evidence-and-source-map.md)
- [재현 빌드 검증 절차](docs/reproducibility.md)

## 라이선스

이 저장소의 자체 제작 코드, 빌드 스크립트와 테스트 코드는 [MIT License](LICENSE)로 배포합니다.

MIT License에 따라 사용·수정·재배포가 가능하며, 재배포 시에는 기존 저작권 고지와 라이선스 문구를 유지하면 됩니다.

이 저장소에 포함된 분석 자료, 패치 데이터, 번역 및 기타 프로젝트 자료는 원작을 분석해 제작된 자료를 포함할 수 있습니다. 원작 게임의 프로그램, D88/ROM 내용, 원문 텍스트, 이미지, 음악, 캐릭터, 상표 등 제3자 저작물의 권리는 각 권리자에게 있습니다.

이 저장소는 원본 상용 게임의 D88/ROM 이미지를 배포하지 않으며, 빌드에 필요한 원본 미디어는 사용자가 직접 준비해야 합니다.

## 주의
이 빌드는 비공식 한글 패치 빌드이며, 모든 권리는 각 권리자에게 있습니다.
