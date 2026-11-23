/**
 * M10 서버 열기 + 인스턴스 불러오기 — 프런트·백엔드 공통 타입.
 */
export const SERVER_HOST_PATH = '/services/integrated-studio/server-host';
export const ServerHostService = Symbol('ServerHostService');

/** A 전용 서버 / B 싱글 LAN 공개 / C 외부 서버(다른 런처로 연 월드·서버) */
export type ServerKind = 'dedicated' | 'lan' | 'external';
export type ProviderId = 'e4mc' | 'upnp' | 'playit';

export type ServerState =
    | 'stopped' | 'needs-eula' | 'preparing' | 'starting' | 'waiting-lan' | 'running' | 'error';

export type AddressState = 'closed' | 'opening' | 'open' | 'failed';

export interface AddressAttempt {
    provider: ProviderId;
    ok: boolean;
    /** 실패하면 다음 방식으로 넘어간 이유(한국어) */
    reason?: string;
}

export interface AddressView {
    state: AddressState;
    provider?: ProviderId;
    /** 친구가 멀티플레이에 넣을 주소 */
    address?: string;
    /** 고정 주소(UPnP+DDNS, playit) / 매번 바뀜(e4mc, DDNS 없는 UPnP) */
    fixed?: boolean;
    /** 직접(UPnP) / 중계(e4mc·playit) */
    relay?: boolean;
    attempts: AddressAttempt[];
    notes: string[];
    /** 지금 시도 중인 방식 */
    trying?: ProviderId;
}

export interface ClientMod {
    id: string;
    name: string;
    version?: string;
    file: string;
    library?: boolean;
}

export interface ServerView {
    id: string;
    kind: ServerKind;
    name: string;
    instanceId?: string;
    instanceName?: string;
    version?: string;
    loader?: string;
    /** 방식 A: 사이드카 서버 id */
    serverId?: string;
    onlineMode?: boolean;
    world?: string | null;
    /** 게임(서버)이 이 PC 에서 듣는 포트 */
    gamePort?: number;
    state: ServerState;
    message?: string;
    eulaUrl?: string;
    players: string[];
    playersOnline?: number;
    maxPlayers?: number;
    motd?: string;
    serverVersion?: string;
    address: AddressView;
    /** 참가자도 같은 모드가 필요한 목록 */
    clientMods: ClientMod[];
    /** 주소 여는 방식 선호(auto = 자동 순서) */
    preference: 'auto' | ProviderId;
}

export interface LanGame {
    /** 신호를 보낸 곳(이 PC 면 true) */
    local: boolean;
    host: string;
    port: number;
    motd: string;
    lastSeen: number;
}

export interface PlayitStatus {
    agentInstalled: boolean;
    agentRunning: boolean;
    /** 계정 연결(비밀키) 됨 */
    linked: boolean;
    claimUrl?: string;
    message?: string;
}

export interface UpnpSettings {
    /** 무료 DDNS 갱신 주소. {ip} {token} {domain} 를 바꿔 넣는다. 예: https://www.duckdns.org/update?domains={domain}&token={token}&ip={ip} */
    ddnsUrl?: string;
    ddnsDomain?: string;
    /** 토큰은 앱 데이터 폴더에만 저장(화면에는 마스킹) */
    hasToken?: boolean;
}

export interface HostSnapshot {
    servers: ServerView[];
    lanGames: LanGame[];
    playit: PlayitStatus;
    upnp: UpnpSettings & { publicIp?: string };
}

export interface CreateServerOptions {
    kind: ServerKind;
    instanceId?: string;
    name?: string;
    onlineMode?: boolean;
    world?: string;
    /** 방식 C: 이 PC 의 포트 */
    port?: number;
    preference?: 'auto' | ProviderId;
}

/** 서버 목록 핑(Server List Ping) 결과 */
export interface PingResult {
    ok: boolean;
    version?: string;
    protocol?: number;
    motd?: string;
    online?: number;
    max?: number;
    players?: string[];
    latencyMs?: number;
    error?: string;
}

/** e4mc 설치 전 사용자가 골라야 할 것 */
export interface E4mcPrepare {
    ok: boolean;
    needsChoice?: boolean;
    conflicts?: Array<{ id: string; name: string; why: string; file: string }>;
    ambiguous?: Array<{ versionId: string; filename: string; versionNumber?: string }>;
    fallback?: boolean;
    reason?: string;
    hostProfile?: { ok: boolean; versionId?: string; message?: string };
    installed?: string[];
}

// ---------------------------------------------------------------- 인스턴스 불러오기
export type LauncherId = 'prism' | 'multimc' | 'curseforge' | 'modrinth' | 'official' | 'folder';

export interface DetectedInstance {
    key: string;
    launcher: LauncherId;
    launcherName: string;
    name: string;
    source: string;
    gameDir: string | null;
    version: string | null;
    loader: string;
    loaderVersion: string | null;
    mods: number;
    lastPlayed: string | null;
    memoryMb: number | null;
    javaArgs: string | null;
    supported: boolean;
    note?: string;
    importedAs?: string | null;
}

export interface ImportPreview {
    mode: 'copy' | 'link';
    items: Array<{ key: string; name: string; launcherName: string; version: string | null; loader: string;
        items: Array<{ name: string; bytes: number }>; bytes: number; gameDir: string | null; supported: boolean; note?: string }>;
    bytes: number;
    warnings: string[];
}

export interface ImportResult {
    imported: Array<{ id: string; name: string; version: string; loader: string; path: string; linkedDir?: string | null; warning?: string }>;
    failed: Array<{ key: string; name: string; error: string }>;
}

export interface ServerHostClient {
    onSnapshot(s: HostSnapshot): void;
    onConsole(id: string, line: string): void;
}

export interface ServerHostService {
    snapshot(): Promise<HostSnapshot>;
    createServer(o: CreateServerOptions): Promise<ServerView>;
    startServer(id: string): Promise<ServerView>;
    stopServer(id: string): Promise<ServerView>;
    deleteServer(id: string): Promise<void>;
    acceptEula(id: string): Promise<ServerView>;
    command(id: string, command: string): Promise<void>;
    console(id: string): Promise<string[]>;
    openAddress(id: string): Promise<ServerView>;
    closeAddress(id: string): Promise<ServerView>;
    setPreference(id: string, pref: 'auto' | ProviderId): Promise<ServerView>;
    ping(port: number): Promise<PingResult>;
    /** e4mc 준비(설치·충돌 선택). choice: ask | disable_once | proceed | skip */
    prepareE4mc(id: string, choice: string): Promise<E4mcPrepare>;
    playitStatus(): Promise<PlayitStatus>;
    /** 사용자가 확인한 뒤에만: 공식 배포처에서 에이전트 받기 */
    playitInstall(): Promise<PlayitStatus>;
    /** 계정 연결 링크 만들기(브라우저로 열기) → 연결될 때까지 기다림 */
    playitClaim(): Promise<PlayitStatus>;
    setUpnpSettings(s: { ddnsUrl?: string; ddnsDomain?: string; ddnsToken?: string }): Promise<UpnpSettings>;
    // 불러오기
    importDetect(): Promise<DetectedInstance[]>;
    importInspectFolder(path: string): Promise<DetectedInstance[]>;
    importPreview(keys: string[], mode: 'copy' | 'link'): Promise<ImportPreview>;
    importRun(entries: Array<{ key: string; name?: string; version?: string }>, mode: 'copy' | 'link'): Promise<ImportResult>;
}

export function formatBytes(n: number): string {
    if (n < 1024) {
        return `${n} B`;
    }
    const units = ['KB', 'MB', 'GB', 'TB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export const PROVIDER_LABEL: Record<ProviderId, string> = { e4mc: 'e4mc 중계', upnp: '직접 UPnP', playit: 'playit 중계' };
