# 통합 작업실 (Integrated Studio)

마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩 — Eclipse Theia 기반 개인용 데스크톱 앱.
작업 지시는 [CLAUDE.md](CLAUDE.md)를 따른다.

## 실행 (개발용)

```
npm install
npm run rebuild -w integrated-studio-electron   # native 모듈을 Electron용으로 재빌드
npm run build
npm start
```

- Theia 1.77.0 / Electron 44.9.1 / Node 22~24
- Windows: Visual Studio Build Tools(C++ 데스크톱 개발) 필요
- Linux: `libxkbfile-dev libx11-dev libsecret-1-dev pkg-config` 필요
