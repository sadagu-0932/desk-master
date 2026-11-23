import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { Emitter } from '@theia/core/lib/common/event';
import { P2PClient, P2PService, P2PSnapshot } from '../common/index.js';

/** 백엔드 알림을 받는 쪽(창마다 하나). */
@injectable()
export class P2PClientImpl implements P2PClient {
    readonly onSnapshotEmitter = new Emitter<P2PSnapshot>();
    readonly onConsoleEmitter = new Emitter<{ id: string; line: string }>();
    onSnapshot(s: P2PSnapshot): void {
        this.onSnapshotEmitter.fire(s);
    }
    onConsole(id: string, line: string): void {
        this.onConsoleEmitter.fire({ id, line });
    }
}

/** 화면이 보는 상태. */
@injectable()
export class P2PStore {
    @inject(P2PService) readonly service: P2PService;
    @inject(P2PClientImpl) protected readonly client: P2PClientImpl;

    snapshot: P2PSnapshot = { hosts: [], joins: [], relays: 0 };
    consoles = new Map<string, string[]>();
    protected readonly changeEmitter = new Emitter<void>();
    readonly onDidChange = this.changeEmitter.event;

    @postConstruct()
    protected init(): void {
        this.client.onSnapshotEmitter.event(s => {
            this.snapshot = s;
            this.changeEmitter.fire();
        });
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

    async refresh(): Promise<void> {
        try {
            this.snapshot = await this.service.snapshot();
            this.changeEmitter.fire();
        } catch {
            // 백엔드 준비 전
        }
    }

    async loadConsole(id: string): Promise<void> {
        this.consoles.set(id, await this.service.console(id));
        this.changeEmitter.fire();
    }
}
