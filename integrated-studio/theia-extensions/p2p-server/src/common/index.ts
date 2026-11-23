/** M10 P2P 서버 — 프런트·백엔드 공용 타입. */
export const P2P_SERVICE_PATH = '/services/integrated-studio/p2p';

export type HostKind = 'dedicated' | 'lan';
export type HostState = 'stopped' | 'needs-eula' | 'preparing' | 'starting' | 'waiting-lan' | 'open' | 'error';
export type LinkMode = 'direct' | 'relay';

export interface PeerView {
    id: string;
    since: number;
    rtt?: number;
    connections: number;
    bytesIn: number;
    bytesOut: number;
}

export interface HostView {
    id: string;
    instanceId: string;
    instanceName: string;
    kind: HostKind;
    name: string;
    code: string;
    state: HostState;
    version: string;
    loader: string;
    /** 방식 A: 사이드카 서버 id·옵션 */
    serverId?: string;
    onlineMode?: boolean;
    world?: string | null;
    /** 마인크래프트가 실제로 듣는 포트(호스트 본인은 127.0.0.1:이 포트로 접속) */
    gamePort?: number;
    players: string[];
    peers: PeerView[];
    traffic: { bytesIn: number; bytesOut: number };
    message?: string;
    eulaUrl?: string;
}

/** 프로토콜 v1 정보 응답 */
export interface JoinInfo {
    proto: number;
    name: string;
    version: string;
    loader: string;
    mode: 'dedicated' | 'lan' | 'external';
    players: number;
    max: number;
}

export interface JoinView {
    id: string;
    code: string;
    state: 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error';
    mode?: LinkMode;
    rtt?: number;
    localPort?: number;
    info?: JoinInfo;
    traffic: { bytesIn: number; bytesOut: number };
    message?: string;
}

export interface P2PSnapshot {
    hosts: HostView[];
    joins: JoinView[];
    relays: number;
}

export interface CreateHostOptions {
    instanceId: string;
    kind: HostKind;
    name?: string;
    onlineMode?: boolean;
    world?: string;
}

export interface P2PService {
    snapshot(): Promise<P2PSnapshot>;
    createHost(opts: CreateHostOptions): Promise<HostView>;
    startHost(id: string): Promise<HostView>;
    stopHost(id: string): Promise<HostView>;
    deleteHost(id: string): Promise<void>;
    regenerateCode(id: string): Promise<HostView>;
    acceptEula(id: string): Promise<HostView>;
    /** 서버 키를 파일로 내보내기/가져오기(재설치·다른 PC 에서도 같은 참가 코드) */
    exportKey(id: string, filePath: string): Promise<{ path: string; code: string }>;
    importKey(id: string, filePath: string): Promise<HostView>;
    command(id: string, command: string): Promise<void>;
    setWorld(id: string, world: string): Promise<HostView>;
    console(id: string): Promise<string[]>;
    join(code: string): Promise<JoinView>;
    leave(id: string): Promise<void>;
    addToServerList(joinId: string, instanceId: string): Promise<{ name: string; ip: string }>;
    setClient(client: P2PClient | undefined): void;
}

export const P2PService = Symbol('P2PService');

export interface P2PClient {
    onSnapshot(snapshot: P2PSnapshot): void;
    onConsole(hostId: string, line: string): void;
}

export function formatBytes(n: number): string {
    if (n < 1024) {
        return `${n} B`;
    }
    if (n < 1024 * 1024) {
        return `${(n / 1024).toFixed(1)} KB`;
    }
    if (n < 1024 * 1024 * 1024) {
        return `${(n / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
