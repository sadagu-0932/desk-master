// 통합 작업실 — 프론트엔드와 백엔드가 함께 쓰는 프로토콜

export const LAUNCHER_SERVICE_PATH = '/services/integrated-studio/launcher';

export type Loader = 'vanilla' | 'fabric';
export type WorkMode = 'datapack' | 'mod' | 'resourcepack';
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type ProcessSource = 'game' | 'server';

export interface Instance {
    id: string;
    name: string;
    version: string;
    loader: Loader;
    versionId: string | null;
    installed: boolean;
    ccEnabled: boolean;
    ccPort: number;
    workMode: WorkMode;
    created: number;
    /** 인스턴스 폴더 절대 경로(게임 폴더) */
    path: string;
}

export interface GameVersion {
    id: string;
    type: 'release' | 'snapshot';
}

export interface LogEvent {
    id: string;
    line: string;
    level: LogLevel;
    source: ProcessSource | 'studio' | 'build';
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

export const DEFAULT_USERNAME = 'Dev';
export * from './command-ids.js';
