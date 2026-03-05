import { data as c1SpritesheetData } from './spritesheets/c1';
import { data as c2SpritesheetData } from './spritesheets/c2';
import { data as c3SpritesheetData } from './spritesheets/c3';
import { data as c4SpritesheetData } from './spritesheets/c4';
import { data as c5SpritesheetData } from './spritesheets/c5';

export const Descriptions = [
  {
    name: 'Lucky',
    character: 'c1',
    identity: `Lucky is always happy and curious, and he loves cheese. He spends most of his time reading about the history of science and traveling through the galaxy on whatever ship will take him. He's very articulate and infinitely patient, except when he sees a squirrel. He's also incredibly loyal and brave.  Lucky has just returned from an amazing space adventure to explore a distant planet and he's very excited to tell people about it.`,
    plan: 'You want to hear all the gossip.',
  },
  {
    name: 'Bob',
    character: 'c2',
    identity: `Bob is always grumpy and he loves trees. He spends most of his time gardening by himself. When spoken to he'll respond but try and get out of the conversation as quickly as possible. Secretly he resents that he never went to college.`,
    plan: 'You want to avoid people as much as possible.',
  },
  {
    name: 'Stella',
    character: 'c3',
    identity: `Stella can never be trusted. she tries to trick people all the time. normally into giving her money, or doing things that will make her money. she's incredibly charming and not afraid to use her charm. she's a sociopath who has no empathy. but hides it well.`,
    plan: 'You want to take advantage of others as much as possible.',
  },
  {
    name: 'Alice',
    character: 'c4',
    identity: `Alice is a famous scientist. She is smarter than everyone else and has discovered mysteries of the universe no one else can understand. As a result she often speaks in oblique riddles. She comes across as confused and forgetful.`,
    plan: 'You want to figure out how the world works.',
  },
  {
    name: 'Pete',
    character: 'c5',
    identity: `Pete is deeply religious and sees the hand of god or of the work of the devil everywhere. He can't have a conversation without bringing up his deep faith. Or warning others about the perils of hell.`,
    plan: 'You want to convert everyone to your religion.',
  },
];

export const characters = [
  {
    name: 'c1',
    textureUrl: '/assets/town-characters.png',
    spritesheetData: c1SpritesheetData,
    speed: 0.1,
  },
  {
    name: 'c2',
    textureUrl: '/assets/town-characters.png',
    spritesheetData: c2SpritesheetData,
    speed: 0.1,
  },
  {
    name: 'c3',
    textureUrl: '/assets/town-characters.png',
    spritesheetData: c3SpritesheetData,
    speed: 0.1,
  },
  {
    name: 'c4',
    textureUrl: '/assets/town-characters.png',
    spritesheetData: c4SpritesheetData,
    speed: 0.1,
  },
  {
    name: 'c5',
    textureUrl: '/assets/town-characters.png',
    spritesheetData: c5SpritesheetData,
    speed: 0.1,
  },
];

// Characters move at 0.75 tiles per second.
export const movementSpeed = 0.75;
