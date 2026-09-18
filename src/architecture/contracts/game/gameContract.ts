interface Game {
    startGame(): void;
    endGame(): void;
    updateGame(deltaTime: number): void;
    renderGame(): void;
}
