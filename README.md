# PC-88 몽환전사 바리스 1 한글패치 빌드
<p align="center">
  <img src="image/Mugen_Senshi_Valis_Disk_A(K)0000.png">

</p>
이 빌드는 PC-88판 《몽환전사 바리스 1》의 원본 이미지를 한글 패치로 적용하는 Python 기반 빌드입니다.

이 빌드는 사용자가 제공한 원본 D88과 `KANJI1.ROM`을 읽고, 분석과 디버거 확인을 거쳐 확정한 직접 바이트 패치표를 원본 이미지에 적용합니다. 여타 다른 현지화 패치와 달리 직접 디스크 섹터의 데이터를 수정하는 방식으로 진행됩니다.

원본 이미지는 `QUASI88 0.7.4`의 디버그 기능을 사용해서 분석되었습니다.

분석한 원본 이미지의 정보는 `source/media/d88-layout.json`, `KANJI1.ROM`은 `source/media/kanji1-layout.json`의 레이아웃을 확인하세요.

## 빌드 구성

- `analysis/`: 분석 근거 장부와 디버거 관찰 자료
- `source/`: 원문·한글 번역·제어 토큰·직접 바이트·KANJI1 글리프 원천표
- `tools/valis_rebuild/`: D88 처리기, 원본 바이트 검사기, 직접 기록기, ROM 생성기
- `tests/`: 소스·구조·직렬화·통합 검증
- `docs/`: 작업 문서

## 빌드 원칙

```text
분석 근거와 디버거 확인
        ↓ 수동 검토
확정된 원문·한글 번역·토큰·직접 바이트 표
        ↓ 원본 바이트 대조
원본 D88/ROM 복사본에 직접 기록
        ↓ 구조·해시·테스트 검증
재현된 D88/ROM
```

## 실행

저장소 루트에서 실행합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild source-lint
PYTHONPATH=. python -m tools.valis_rebuild text-lint
PYTHONPATH=. python -m unittest discover -s tests -v
```

원본 D88과 KANJI1 ROM을 지정해 빌드합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild build \
  --d88 /path/to/original.d88 \
  --rom /path/to/KANJI1.ROM \
  --out build/reproduction
```

현재 `import/KANJI1.ROM`을 입력으로 사용해 글리프 ROM을 `output/`에 만들려면 다음을 실행합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild build-rom \
  --rom import/KANJI1.ROM \
  --out output \
  --allow-input-hash-mismatch
```

이 ROM은 기준 입력 SHA-256과 다르므로 결과 보고서는 `input_matches_baseline: false`로 기록합니다. 크기는 검증하며, 해당 ROM에 명시된 476개 글리프를 기록합니다.

출력을 검증합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild verify \
  --d88 "build/reproduction/d88/valis_disk_a(K).d88" \
  --rom "build/reproduction/kanji/KANJI1(K).ROM"
```

결과를 기준 파일과 대조합니다.

```sh
PYTHONPATH=. python -m tools.valis_rebuild compare \
  --built "build/reproduction/d88/valis_disk_a(K).d88" \
  --reference /path/to/reference.d88 \
  --fail-on-diff
```

## 결과물과 보관 범위

빌드 결과는 `build/` 아래에 생성합니다.

## 문서

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
