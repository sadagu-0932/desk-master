import { inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { ConfirmDialog } from '@theia/core/lib/browser/dialogs';
import { Instance } from '../common/index.js';
import { CreateInstanceDialog } from './create-instance-dialog.js';
import { InstanceManager } from './instance-manager.js';

const CATEGORY = '통합 작업실';

export namespace StudioCommands {
    export const CREATE: Command = { id: 'studio.instance.create', category: CATEGORY, label: '새 인스턴스 만들기' };
    export const INSTALL: Command = { id: 'studio.instance.install', category: CATEGORY, label: '인스턴스 설치(게임 파일 받기)' };
    export const LAUNCH: Command = { id: 'studio.instance.launch', category: CATEGORY, label: '실행' };
    export const STOP: Command = { id: 'studio.instance.stop', category: CATEGORY, label: '중지' };
    export const RESTART: Command = { id: 'studio.instance.restart', category: CATEGORY, label: '재시작' };
    export const SELECT_TARGET: Command = { id: 'studio.instance.selectTarget', category: CATEGORY, label: '실행 대상 바꾸기' };
    export const OPEN_WORKSPACE: Command = { id: 'studio.instance.openWorkspace', category: CATEGORY, label: '작업실에서 열기' };
    export const RENAME: Command = { id: 'studio.instance.rename', category: CATEGORY, label: '인스턴스 이름 바꾸기' };
    export const DELETE: Command = { id: 'studio.instance.delete', category: CATEGORY, label: '인스턴스 삭제(휴지통)' };
    export const TOGGLE_CC: Command = { id: 'studio.instance.toggleCommandCrafter', category: CATEGORY, label: 'CommandCrafter 모드 켜기/끄기' };
    export const REFRESH: Command = { id: 'studio.instance.refresh', category: CATEGORY, label: '인스턴스 목록 새로고침' };
    export const SIDECAR_STATUS: Command = { id: 'studio.sidecar.status', category: CATEGORY, label: '사이드카 상태 보기' };
}

/** 명령 인자는 인스턴스 id(문자열)이거나 없으면 현재 인스턴스 */
type IdArg = string | undefined;

@injectable()
export class LauncherCommandContribution implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(MessageService) protected readonly messages: MessageService;

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(StudioCommands.CREATE, { execute: () => this.guard(() => this.create()) });
        registry.registerCommand(StudioCommands.INSTALL, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                await this.manager.install(i.id);
                this.messages.info(`${i.name} 설치가 끝났습니다.`);
            })
        });
        registry.registerCommand(StudioCommands.LAUNCH, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.launch(i.id)),
            isEnabled: (id: IdArg) => !this.manager.isRunning(this.resolve(id)?.id),
        });
        registry.registerCommand(StudioCommands.STOP, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.stop(i.id)),
            isEnabled: (id: IdArg) => this.manager.isRunning(this.resolve(id)?.id),
        });
        registry.registerCommand(StudioCommands.RESTART, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.restart(i.id)),
        });
        registry.registerCommand(StudioCommands.SELECT_TARGET, { execute: () => this.guard(() => this.selectTarget()) });
        registry.registerCommand(StudioCommands.OPEN_WORKSPACE, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.openInWorkspace(i.id))
        });
        registry.registerCommand(StudioCommands.RENAME, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const name = await this.quickInput.input({ prompt: '새 이름', value: i.name });
                if (name) {
                    await this.manager.rename(i.id, name);
                }
            })
        });
        registry.registerCommand(StudioCommands.DELETE, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                if (this.manager.isRunning(i.id)) {
                    this.messages.warn('실행 중인 인스턴스는 삭제할 수 없습니다. 먼저 중지하세요.');
                    return;
                }
                const ok = await new ConfirmDialog({
                    title: '인스턴스 삭제',
                    msg: `'${i.name}' 인스턴스 폴더를 휴지통으로 옮길까요? (월드·데이터팩 포함)`,
                    ok: '휴지통으로', cancel: '취소',
                }).open();
                if (ok) {
                    await this.manager.delete(i.id);
                }
            })
        });
        registry.registerCommand(StudioCommands.TOGGLE_CC, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                if (i.loader !== 'fabric') {
                    this.messages.info('CommandCrafter 모드는 Fabric 인스턴스에서만 쓸 수 있습니다.');
                    return;
                }
                await this.manager.setCcEnabled(i.id, !i.ccEnabled);
                this.messages.info(`CommandCrafter 모드: ${!i.ccEnabled ? '켬' : '끔'} (다음 실행부터 적용)`);
            })
        });
        registry.registerCommand(StudioCommands.REFRESH, { execute: () => this.manager.refresh() });
        registry.registerCommand(StudioCommands.SIDECAR_STATUS, {
            execute: async () => {
                const s = await this.manager.call<{ version: string; data: string }>('ping').catch(e => e as Error);
                if (s instanceof Error) {
                    this.messages.error(`사이드카 오류: ${s.message}`);
                } else {
                    this.messages.info(`사이드카 ${s.version} 정상 · 데이터 폴더: ${s.data}`);
                }
            }
        });
    }

    resolve(id: IdArg): Instance | undefined {
        return typeof id === 'string' ? this.manager.find(id) : this.manager.current;
    }

    protected async withInstance(id: IdArg, fn: (inst: Instance) => Promise<unknown>): Promise<void> {
        await this.manager.ready;
        let inst = this.resolve(id);
        if (!inst) {
            if (this.manager.instances.length === 0) {
                this.messages.info('인스턴스가 없습니다. 먼저 새 인스턴스를 만드세요.', '새 인스턴스 만들기').then(a => {
                    if (a) { this.guard(() => this.create()); }
                });
                return;
            }
            inst = await this.pickInstance();
            if (!inst) {
                return;
            }
        }
        const target = inst;
        await this.guard(() => fn(target));
    }

    protected async guard(fn: () => Promise<unknown>): Promise<void> {
        try {
            await fn();
        } catch (e) {
            this.messages.error(e instanceof Error ? e.message : String(e));
        }
    }

    async pickInstance(placeholder = '인스턴스 선택'): Promise<Instance | undefined> {
        await this.manager.ready;
        const items = this.manager.instances.map(i => ({
            label: i.name,
            description: `Java ${i.version} · ${i.loader === 'fabric' ? 'Fabric' : '바닐라'}${this.manager.isRunning(i.id) ? ' · 실행 중' : ''}`,
            id: i.id,
        }));
        const picked = await this.quickInput.showQuickPick(items, { placeholder });
        return picked ? this.manager.find(picked.id) : undefined;
    }

    protected async selectTarget(): Promise<void> {
        const inst = await this.pickInstance('실행 대상 선택');
        if (inst) {
            await this.manager.setTarget(inst.id);
        }
    }

    /** 새 인스턴스 창(Prism Launcher의 "인스턴스 추가" 배치 참고) */
    protected async create(): Promise<void> {
        await this.manager.ready;
        const groups = [...new Set(this.manager.instances.map(i => i.group).filter((g): g is string => !!g))];
        const result = await new CreateInstanceDialog(this.manager, groups).open();
        if (!result) {
            return;
        }
        const inst = await this.manager.create(result.options);
        if (result.installNow) {
            // 설치는 뒤에서 진행(진행률은 알림에 표시). 창을 막지 않는다
            this.manager.install(inst.id)
                .then(() => this.messages.info(`'${inst.name}' 설치가 끝났습니다. F5로 실행하세요.`, '작업실에서 열기')
                    .then(a => a && this.manager.openInWorkspace(inst.id)))
                .catch(e => this.messages.error(`'${inst.name}' 설치 실패: ${e instanceof Error ? e.message : e}`));
        } else {
            const action = await this.messages.info(`'${inst.name}' 인스턴스를 만들었습니다. 처음 실행할 때 게임 파일을 받습니다.`, '작업실에서 열기');
            if (action) {
                await this.manager.openInWorkspace(inst.id);
            }
        }
    }
}
