import { Command } from '@theia/core/lib/common/command';

const CATEGORY = '통합 작업실';

export namespace ServerHostCommands {
    export const TOGGLE: Command = { id: 'studio.serverHost.toggle', category: CATEGORY, label: '서버 패널 열기' };
    export const OPEN_SERVER: Command = { id: 'studio.serverHost.open', category: CATEGORY, label: '서버 열기' };
    export const IMPORT: Command = { id: 'studio.serverHost.import', category: CATEGORY, label: '다른 런처 인스턴스 불러오기' };
    export const PLAYIT_SETUP: Command = { id: 'studio.serverHost.playit', category: CATEGORY, label: 'playit 준비·계정 연결' };
    export const DDNS: Command = { id: 'studio.serverHost.ddns', category: CATEGORY, label: 'UPnP 고정 주소(DDNS) 설정' };
    export const START: Command = { id: 'studio.serverHost.start' };
    export const EULA: Command = { id: 'studio.serverHost.eula' };
    export const OPEN_LAN: Command = { id: 'studio.serverHost.openLan' };
    export const HOST_INSTANCE: Command = { id: 'studio.serverHost.hostInstance' };
}
