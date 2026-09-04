const assert = require('assert');
const engine = require('../draft-engine.js');

assert.deepStrictEqual(engine.snakePicks(10, 3, 10), [3,18,23,38,43,58,63,78,83,98]);
assert.strictEqual(engine.nextPick(4, engine.snakePicks(10,3,10)), 18);
assert.strictEqual(engine.nextPick(18, engine.snakePicks(10,3,10)), 18);
assert.strictEqual(engine.stableId('A Player','WR','BUF'), engine.stableId('A Player','WR','BUF'));
const csv = 'Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted\r\n"Doe, John",WR,BUF,2,3.5,4,Yes,,,No\r\nJane Doe,RB,NYJ,1,2,2,,Yes,,Yes';
const players = engine.parseCSV(csv);
assert.strictEqual(players.length, 2);
assert.strictEqual(players[1].player, 'Doe, John');
assert.strictEqual(players[1].target, true);
assert.strictEqual(players[0].drafted, true);
console.log('All draft engine tests passed.');
