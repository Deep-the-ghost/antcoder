export class Timer {
    private startTime: number | null = null;

    startTimer(): void {
        this.startTime = performance.now();
    }

    stopTimer(): void {
        if (this.startTime !== null) {
            this.startTime = null;
        }
    }

    getDeltaTime(): number {
        const now = performance.now();
        return this.startTime !== null ? now - this.startTime : 0;
    }
}
