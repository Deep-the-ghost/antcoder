export interface Level {
    loadLevel(levelData: LevelData): void;
    updateLevel(deltaTime: number): void;
    renderLevel(): void;
}
