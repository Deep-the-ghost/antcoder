class Game {
    private level: Level;
    private entities: Entity[];
    private input: Input;
    private renderer: Renderer;
    private timer: Timer;

    constructor(level: Level, entities: Entity[], input: Input, renderer: Renderer, timer: Timer) {
        this.level = level;
        this.entities = entities;
        this.input = input;
        this.renderer = renderer;
        this.timer = timer;
    }

    startGame(): void {
        this.level.loadLevel(this.level.levelData);
        this.timer.startTimer();
        this.input.handleInput();
    }

    endGame(): void {
        this.timer.stopTimer();
    }

    updateGame(deltaTime: number): void {
        this.level.updateLevel(deltaTime);
        this.entities.forEach(entity => entity.update(deltaTime));
        this.input.handleInput();
    }

    renderGame(): void {
        this.renderer.renderLevel(this.level);
        this.renderer.renderEntities(this.entities);
    }
}
