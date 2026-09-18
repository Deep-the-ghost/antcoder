export interface Renderer {
    renderEntities(entities: Entity[]): void;
    renderLevel(level: Level): void;
}
