import { Command } from '@theia/core/lib/common/command';

const CATEGORY = '통합 작업실';

export namespace P2PCommands {
    export const TOGGLE: Command = { id: 'studio.p2p.toggle', category: CATEGORY, label: 'P2P 서버 패널 열기' };
    export const HOST: Command = { id: 'studio.p2p.host', category: CATEGORY, label: 'P2P 서버 열기' };
    export const JOIN: Command = { id: 'studio.p2p.join', category: CATEGORY, label: 'P2P 서버 참가(코드)' };
    export const START: Command = { id: 'studio.p2p.start' };
    export const EULA: Command = { id: 'studio.p2p.eula' };
    export const PLAY: Command = { id: 'studio.p2p.play' };
    export const EXPORT_KEY: Command = { id: 'studio.p2p.exportKey' };
    export const IMPORT_KEY: Command = { id: 'studio.p2p.importKey' };
}
