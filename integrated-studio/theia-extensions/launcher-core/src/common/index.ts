// 통합 작업실 — 프론트엔드와 백엔드가 함께 쓰는 프로토콜

export const LAUNCHER_SERVICE_PATH = '/services/integrated-studio/launcher';

export type Loader = 'vanilla' | 'fabric' | 'quilt' | 'neoforge' | 'forge';  // quilt·neoforge·forge 는 다른 런처에서 불러온 인스턴스

export const LOADER_LABELS: Record<string, string> = { vanilla: '바닐라', fabric: 'Fabric', quilt: 'Quilt', neoforge: 'NeoForge', forge: 'Forge' };
export type WorkMode = 'datapack' | 'mod' | 'resourcepack';
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type ProcessSource = 'game' | 'server';

export interface Instance {
    id: string;
    name: string;
    version: string;
    loader: Loader;
    /** Fabric 로더 버전(없으면 설치 때 최신 안정판) */
    loaderVersion?: string | null;
    group?: string | null;
    /** 카드·목록에 쓰는 아이콘 색 #RRGGBB */
    icon?: string | null;
    versionId: string | null;
    installed: boolean;
    ccEnabled: boolean;
    ccPort: number;
    workMode: WorkMode;
    created: number;
    /** 인스턴스 폴더 절대 경로(게임 폴더) */
    path: string;
    /** "연결"로 불러온 인스턴스: 다른 런처의 원본 게임 폴더(이때 path 와 같다) */
    linkedDir?: string | null;
    /** 공식 런처 항목에 넣는 JVM 인자(최대 메모리 -Xmx 등) */
    jvmArgs?: string | null;
    /** 연결한 Prism·MultiMC 인스턴스: 그 런처로 바로 실행(이 앱에 설치하지 않음) */
    launchVia?: { kind: 'prism' | 'multimc'; root?: string | null; instance: string } | null;
    /** 연결한 원래 인스턴스 폴더(실행 파일이 있는 곳) */
    sourceDir?: string | null;
    /** 원래 폴더 안에 만든 실행 파일 — [실행]하면 이 파일이 원래 런처를 연다 */
    launchFile?: string | null;
    /** 실행 파일이 여는 런처 */
    launchKind?: 'prism' | 'multimc' | 'curseforge' | 'modrinth' | 'official' | null;
}

export interface GameVersion {
    id: string;
    type: 'release' | 'snapshot' | 'old_beta' | 'old_alpha';
    /** 출시일 YYYY-MM-DD */
    released: string;
}

export interface LoaderVersions {
    supported: boolean;
    versions: { version: string; stable: boolean }[];
}

export interface CreateInstanceOptions {
    name: string;
    version: string;
    loader: Loader;
    loaderVersion?: string;
    group?: string;
    icon?: string;
    ccEnabled?: boolean;
}

export interface LogEvent {
    id: string;
    line: string;
    level: LogLevel;
    source: ProcessSource | 'studio' | 'build' | 'official';
}

/** 사이드카가 사용자에게 묻는 확인(공식 런처 설치·등록 등). 답은 confirm_reply(token, ok) */
export interface ConfirmEvent {
    token: string;
    id: string;
    title?: string;
    message: string;
}

export interface StateEvent {
    id: string;
    source: ProcessSource;
    running: boolean;
    pid?: number;
    exitCode?: number;
}

export interface ProgressEvent {
    id: string;
    stage: string;
    text?: string;
    value?: number;
    max?: number;
    done?: boolean;
}

export interface ServerStartResult {
    pid?: number;
    needsEula?: boolean;
    eulaPath?: string;
    eulaUrl?: string;
}

export interface SidecarStatus {
    ok: boolean;
    message: string;
    dataDir: string;
    python?: string;
}

export const LauncherClient = Symbol('LauncherClient');
export interface LauncherClient {
    onSidecarNotification(method: string, params: unknown): void;
}

export const LauncherService = Symbol('LauncherService');
export interface LauncherService {
    /** 사이드카 JSON-RPC 메서드 호출 */
    call<T = unknown>(method: string, params?: object): Promise<T>;
    status(): Promise<SidecarStatus>;
    /** 앱에 함께 들어 있는 Claude Agent SDK의 cli.js 경로(없으면 undefined) */
    bundledClaudeSdkCli(): Promise<string | undefined>;
    setClient(client: LauncherClient | undefined): void;
}

export * from './command-ids.js';
