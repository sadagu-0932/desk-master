import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { groupInstances, Instance, LOADER_LABELS } from 'integrated-studio-launcher-core/lib/common';

export const loaderLabel = (i: Instance) => LOADER_LABELS[i.loader] ?? i.loader;

/** 사이드바 아래쪽 "인스턴스" 뷰 */
@injectable()
export class InstancesWidget extends ReactWidget {
    static readonly ID = 'studio-instances';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;

    @postConstruct()
    protected init(): void {
        this.id = InstancesWidget.ID;
        this.title.label = '인스턴스';
        this.title.caption = '인스턴스';
        this.title.closable = false;
        this.addClass('studio-instances');
        this.toDispose.push(this.manager.onDidChange(() => this.update()));
        this.update();
    }

    protected render(): React.ReactNode {
        const { instances, error } = this.manager;
        const target = this.manager.target;
        if (error) {
            return <div className='studio-empty studio-error'>
                <div>사이드카 오류</div>
                <div className='studio-muted'>{error}</div>
                <button className='theia-button secondary' onClick={() => this.manager.refresh()}>다시 시도</button>
            </div>;
        }
        if (instances.length === 0) {
            return <div className='studio-empty'>
                <div className='studio-muted'>아직 인스턴스가 없습니다.</div>
                <button className='theia-button' onClick={() => this.commands.executeCommand(StudioCommands.CREATE.id)}>+ 새 인스턴스</button>
            </div>;
        }
        const sections = groupInstances([...instances]);
        const flat = sections.length === 1 && !sections[0].group;   // 그룹이 하나도 없으면 예전처럼 한 줄 목록
        return <div className='studio-list' role='list' aria-label='인스턴스'>
            {flat ? sections[0].items.map(i => this.renderRow(i, target)) : sections.map(s => this.renderGroup(s.group, s.items, target))}
        </div>;
    }

    /** 끌어다 놓을 인스턴스 id(그룹 머리·그룹 영역에 놓으면 그 그룹으로) */
    static readonly DRAG_TYPE = 'application/x-studio-instance';
    protected dropTarget: string | null = null;

    protected dropProps(group: string | undefined): React.HTMLAttributes<HTMLDivElement> {
        const key = group ?? '';
        return {
            onDragOver: e => {
                if (e.dataTransfer.types.includes(InstancesWidget.DRAG_TYPE)) {
                    e.preventDefault();
                    if (this.dropTarget !== key) { this.dropTarget = key; this.update(); }
                }
            },
            onDragLeave: () => { if (this.dropTarget === key) { this.dropTarget = null; this.update(); } },
            onDrop: e => {
                const id = e.dataTransfer.getData(InstancesWidget.DRAG_TYPE);
                this.dropTarget = null;
                this.update();
                if (id) {
                    e.preventDefault();
                    this.commands.executeCommand(StudioCommands.SET_GROUP.id, id, group ?? null);
                }
            },
        };
    }

    protected renderGroup(group: string | undefined, items: Instance[], target: Instance | undefined): React.ReactNode {
        const name = group ?? '그룹 없음';
        const collapsed = this.manager.isGroupCollapsed('side', name);
        return <div key={name} role='group' aria-label={name}
            className={'studio-group' + (this.dropTarget === (group ?? '') ? ' drop' : '')} {...this.dropProps(group)}>
            <div className='studio-group-head' role='button' tabIndex={0} aria-expanded={!collapsed}
                onClick={() => this.manager.toggleGroup('side', name)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.manager.toggleGroup('side', name); } }}
                title={group ? `${group} — 인스턴스를 여기로 끌어다 놓으면 이 그룹으로` : '그룹에 넣지 않은 인스턴스'}>
                <span className={'codicon ' + (collapsed ? 'codicon-chevron-right' : 'codicon-chevron-down')} aria-hidden='true' />
                <span className={'codicon ' + (group ? (collapsed ? 'codicon-folder' : 'codicon-folder-opened') : 'codicon-inbox')} aria-hidden='true' />
                <span className='studio-group-name'>{name}</span>
                <span className='studio-group-count'>{items.length}</span>
                {group && <>
                    <button className='studio-icon-btn codicon codicon-edit' aria-label={`${group} 이름 바꾸기`} title='그룹 이름 바꾸기'
                        onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.RENAME_GROUP.id, group); }} />
                    <button className='studio-icon-btn codicon codicon-close' aria-label={`${group} 그룹 풀기`} title='그룹 풀기(인스턴스는 그대로)'
                        onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.UNGROUP.id, group); }} />
                </>}
            </div>
            {!collapsed && items.map(i => this.renderRow(i, target))}
        </div>;
    }

    protected renderRow(i: Instance, target: Instance | undefined): React.ReactNode {
        const running = this.manager.isRunning(i.id);
        const server = this.manager.state(i.id).server;
        const sub = running ? `실행 중 · ${loaderLabel(i)}` : `Java ${i.version} · ${loaderLabel(i)}${i.installed ? '' : ' · 설치 전'}`;
        return <div key={i.id} role='listitem' draggable
            onDragStart={e => { e.dataTransfer.setData(InstancesWidget.DRAG_TYPE, i.id); e.dataTransfer.effectAllowed = 'move'; }}
            className={'studio-row' + (target?.id === i.id ? ' active' : '')}
            onClick={() => this.manager.setTarget(i.id)}
            onDoubleClick={() => this.commands.executeCommand(StudioCommands.OPEN_WORKSPACE.id, i.id)}
            onContextMenu={e => { e.preventDefault(); this.commands.executeCommand(StudioCommands.MANAGE.id, i.id); }}
            title={i.path}>
            <span className={'studio-dot' + (running ? ' on' : '') + (server ? ' server' : '')} aria-hidden='true' />
            <span className='studio-row-text'>
                <span className='studio-row-name'>{i.name}</span>
                <span className='studio-row-sub'>{sub}{server ? ' · 서버' : ''}{i.linkedDir ? ' · 연결됨' : ''}</span>
            </span>
            <button className='studio-icon-btn codicon codicon-play' aria-label={`${i.name} 실행 (Prism)`} disabled={running}
                title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : '실행 (F5) — Prism 으로'}
                onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.LAUNCH.id, i.id); }} />
            <button className='studio-icon-btn codicon codicon-folder' aria-label={`${i.name} 폴더 열기`} title='폴더 열기 (파일 탐색기)'
                onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.OPEN_FOLDER.id, i.id); }} />
            <button className='studio-icon-btn codicon codicon-ellipsis' aria-label={`${i.name} 관리`} title='관리 — 이름 바꾸기·복제·메모리·삭제 등 (오른쪽 클릭)'
                onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.MANAGE.id, i.id); }} />
        </div>;
    }
}
