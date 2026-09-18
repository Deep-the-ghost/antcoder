#!/usr/bin/env node

const readline = require('readline');

// Terminal Playable Snake Game
const WIDTH = 26;
const HEIGHT = 16;

let snake = [
  { x: 10, y: 8 },
  { x: 9, y: 8 },
  { x: 8, y: 8 }
];
let direction = { x: 1, y: 0 };
let nextDirection = { x: 1, y: 0 };
let food = spawnFood();
let score = 0;
let gameOver = false;
let gameInterval = null;

function spawnFood() {
  while (true) {
    const x = Math.floor(Math.random() * (WIDTH - 2)) + 1;
    const y = Math.floor(Math.random() * (HEIGHT - 2)) + 1;
    if (!snake.some(segment => segment.x === x && segment.y === y)) {
      return { x, y };
    }
  }
}

function render() {
  let output = '\x1b[H\x1b[2J'; // Clear terminal screen
  output += '\x1b[1;36m╔' + '═'.repeat(WIDTH * 2) + '╗\x1b[0m\n';
  output += '\x1b[1;36m║\x1b[1;33m' + ' 🐜 ANT CODER: SNAKE GAME '.padStart(WIDTH + 14).padEnd(WIDTH * 2) + '\x1b[1;36m║\x1b[0m\n';
  output += '\x1b[1;36m╠' + '═'.repeat(WIDTH * 2) + '╣\x1b[0m\n';

  for (let y = 0; y < HEIGHT; y++) {
    output += '\x1b[1;36m║\x1b[0m';
    for (let x = 0; x < WIDTH; x++) {
      if (x === 0 || x === WIDTH - 1 || y === 0 || y === HEIGHT - 1) {
        output += '\x1b[90m██\x1b[0m'; // Wall
      } else if (snake[0].x === x && snake[0].y === y) {
        output += '\x1b[1;32m🟢\x1b[0m'; // Snake Head
      } else if (snake.some(segment => segment.x === x && segment.y === y)) {
        output += '\x1b[32m🟩\x1b[0m'; // Snake Body
      } else if (food.x === x && food.y === y) {
        output += '🍎'; // Food
      } else {
        output += '  '; // Empty space
      }
    }
    output += '\x1b[1;36m║\x1b[0m\n';
  }

  output += '\x1b[1;36m╠' + '═'.repeat(WIDTH * 2) + '╣\x1b[0m\n';
  output += `\x1b[1;36m║\x1b[1;37m Score: \x1b[1;32m${score}\x1b[0m` + `Length: ${snake.length}`.padStart(WIDTH * 2 - 14) + ' \x1b[1;36m║\x1b[0m\n';
  output += '\x1b[1;36m║\x1b[dim] Controls: [W/A/S/D] or [Arrow Keys] • [Q] Quit           \x1b[1;36m║\x1b[0m\n';
  output += '\x1b[1;36m╚' + '═'.repeat(WIDTH * 2) + '╝\x1b[0m\n';

  if (gameOver) {
    output += '\n\x1b[1;31m💥 GAME OVER! Final Score: ' + score + '\x1b[0m\n';
    output += '\x1b[1;33mPress [R] to Restart or [Q] to Quit.\x1b[0m\n';
  }

  process.stdout.write(output);
}

function update() {
  if (gameOver) return;

  direction = nextDirection;
  const head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };

  // Wall collision
  if (head.x <= 0 || head.x >= WIDTH - 1 || head.y <= 0 || head.y >= HEIGHT - 1) {
    gameOver = true;
    render();
    return;
  }

  // Self collision
  if (snake.some(segment => segment.x === head.x && segment.y === head.y)) {
    gameOver = true;
    render();
    return;
  }

  snake.unshift(head);

  // Food eaten
  if (head.x === food.x && head.y === food.y) {
    score += 10;
    food = spawnFood();
  } else {
    snake.pop();
  }

  render();
}

function restart() {
  snake = [
    { x: 10, y: 8 },
    { x: 9, y: 8 },
    { x: 8, y: 8 }
  ];
  direction = { x: 1, y: 0 };
  nextDirection = { x: 1, y: 0 };
  food = spawnFood();
  score = 0;
  gameOver = false;
  render();
}

// Keypress handling
readline.emitKeypressEvents(process.stdin);
if (process.stdin.isTTY) {
  process.stdin.setRawMode(true);
}

process.stdin.on('keypress', (str, key) => {
  if (key && (key.ctrl && key.name === 'c' || key.name === 'q')) {
    process.stdout.write('\x1b[?25h\nExiting Snake Game. Thanks for playing!\n');
    process.exit();
  }

  if (gameOver) {
    if (key && key.name === 'r') {
      restart();
    }
    return;
  }

  if (!key) return;

  if ((key.name === 'up' || key.name === 'w') && direction.y === 0) {
    nextDirection = { x: 0, y: -1 };
  } else if ((key.name === 'down' || key.name === 's') && direction.y === 0) {
    nextDirection = { x: 0, y: 1 };
  } else if ((key.name === 'left' || key.name === 'a') && direction.x === 0) {
    nextDirection = { x: -1, y: 0 };
  } else if ((key.name === 'right' || key.name === 'd') && direction.x === 0) {
    nextDirection = { x: 1, y: 0 };
  }
});

// Hide cursor and start loop
process.stdout.write('\x1b[?25l');
render();
gameInterval = setInterval(update, 130);

