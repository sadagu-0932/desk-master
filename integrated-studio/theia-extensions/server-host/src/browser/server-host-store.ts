import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { Emitter } from '@theia/core/lib/common/event';
import { HostSnapshot, ServerHostClient, ServerHostService } from '../common/index.js';

/** 백엔드 알림을 받는 쪽(창마다 하나). */
@injectable()
export class ServerHostClientImpl implements ServerHostClient {
    readonly onSnapshotEmitter = new Emitter<HostSnapshot>();
    readonly onConsoleEmitter = new Emitter<{ id: string; line: string }>();
    onSnapshot(s: HostSnapshot): void {
        this.onSnapshotEmitter.fire(s);
    }
    onConsole(id: string, line: string): void {
        this.onConsoleEmitter.fire({ id, line });
    }
}

/** 화면이 보는 상태. */
@injectable()
export class ServerHostStore {
    @inject(ServerHostService) readonly service: ServerHostService;
    @inject(ServerHostClientImpl) protected readonly client: ServerHostClientImpl;

    snapshot: HostSnapshot = { servers: [], lanGames: [], upnp: {} };
    consoles = new Map<string, string[]>();
    protected readonly changeEmitter = new Emitter<void>();
    readonly onDidChange = this.changeEmitter.event;

    @postConstruct()
    protected init(): void {
        this.client.onSnapshotEmitter.event(s => this.set(s));
        this.client.onConsoleEmitter.event(({ id, line }) => {
            const list = this.consoles.get(id) ?? [];
            list.push(line);
            if (list.length > 500) {
                list.splice(0, list.length - 500);
            }
            this.consoles.set(id, list);
            this.changeEmitter.fire();
        });
        this.refresh();
    }

    protected set(s: HostSnapshot): void {
        this.snapshot = s;
        this.changeEmitter.fire();
    }

    async refresh(): Promise<void> {
        try {
            this.set(await this.service.snapshot());
        } catch {
            // 백엔드 준비 전
        }
    }

    async loadConsole(id: string): Promise<void> {
        this.consoles.set(id, await this.service.console(id));
        this.changeEmitter.fire();
    }
}
