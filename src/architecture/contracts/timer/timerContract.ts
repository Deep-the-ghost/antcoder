export interface Timer {
    startTimer(): void;
    stopTimer(): void;
    getDeltaTime(): number;
}
