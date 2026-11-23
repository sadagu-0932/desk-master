// hyperdht · blind-relay · hypercore-id-encoding 은 타입 정의가 없어 여기서 쓰는 부분만 적는다.
declare module 'hyperdht' {
    import { EventEmitter } from 'events';
    import { Duplex } from 'stream';

    export interface KeyPair { publicKey: Buffer; secretKey: Buffer }
    export interface HyperSocket extends Duplex {
        remotePublicKey: Buffer;
        publicKey: Buffer;
        rawStream: { remoteHost?: string; remotePort?: number } | null;
        setKeepAlive(ms: number): void;
        on(event: string, listener: (...args: any[]) => void): this;
        once(event: string, listener: (...args: any[]) => void): this;
    }
    export interface HyperServer extends EventEmitter {
        listen(keyPair: KeyPair): Promise<void>;
        close(): Promise<void>;
        address(): { host: string; port: number; publicKey: Buffer } | null;
    }
    export interface ConnectOptions { keyPair?: KeyPair; relayThrough?: Buffer | Buffer[] | null; nodes?: unknown[] }
    export default class DHT extends EventEmitter {
        constructor(opts?: { bootstrap?: Array<string | { host: string; port: number }>; keyPair?: KeyPair; connectionKeepAlive?: number | false; [k: string]: unknown });
        static keyPair(seed?: Buffer): KeyPair;
        connect(remotePublicKey: Buffer | string, opts?: ConnectOptions): HyperSocket;
        createServer(opts?: { firewall?: (remotePublicKey: Buffer) => boolean; relayThrough?: Buffer | Buffer[] | null }, onconnection?: (socket: HyperSocket) => void): HyperServer;
        createRawStream(opts?: unknown): unknown;
        destroy(opts?: { force?: boolean }): Promise<void>;
        fullyBootstrapped(): Promise<void>;
    }
}

declare module 'hyperdht/testnet.js' {
    import DHT from 'hyperdht';
    export default function createTestnet(size?: number, opts?: unknown): Promise<{
        nodes: DHT[];
        bootstrap: Array<{ host: string; port: number }>;
        createNode(opts?: unknown): DHT;
        destroy(): Promise<void>;
    }>;
}

declare module 'blind-relay' {
    import { EventEmitter } from 'events';
    export class Server extends EventEmitter {
        constructor(opts: { createStream: (opts: unknown) => unknown });
        accept(stream: unknown, opts: { id: Buffer }): EventEmitter;
        close(): Promise<void>;
        stats: Record<string, Record<string, number>>;
    }
}

declare module 'hypercore-id-encoding' {
    export function encode(key: Buffer): string;
    export function decode(id: string): Buffer;
    export function normalize(id: string): string;
    export function isValid(id: string): boolean;
}
