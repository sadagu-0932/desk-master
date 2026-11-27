/** 여러 확장이 함께 쓰는 명령 id. 실제 구현은 각 확장(datapack-tools 등)에 있다. */
export namespace TaskCommandIds {
    export const SERVER_TOGGLE = 'studio.server.toggle';
    export const MOD_BUILD_TEST = 'studio.mod.buildAndTest';
    export const PLUGIN_BUILD_TEST = 'studio.plugin.buildAndTest';
    export const RESOURCEPACK_APPLY = 'studio.resourcepack.apply';
    export const DATAPACK_ZIP = 'studio.datapack.exportZip';
    export const DATAPACK_SYNC = 'studio.datapack.syncToWorld';
    export const GAME_RELOAD = 'studio.game.reload';
    export const GAME_RUN_COMMAND = 'studio.game.runCommand';
    export const HOME_OPEN = 'studio.home.open';
    export const GAME_LOG_TOGGLE = 'studio.gameLog.toggle';
    export const CONSOLE_TOGGLE = 'studio.console.toggle';
    export const CLAUDE_APPLY_RELOAD = 'studio.claude.applyAndReload';
    export const CLAUDE_WORK_MODE = 'studio.claude.workMode';
}
