/**
 * Isol8 endpoint mapping — replaces the Convex-generated api.js
 *
 * Each entry maps to a REST endpoint on the Isol8 backend.
 * _type indicates whether the frontend calls it as a query (GET) or
 * mutation (POST).
 */

export const api = {
  world: {
    worldState: { _type: 'query', endpoint: '/town/state' },
    defaultWorldStatus: { _type: 'query', endpoint: '/town/status' },
    gameDescriptions: { _type: 'query', endpoint: '/town/descriptions' },
    userStatus: { _type: 'query', endpoint: '/town/user-status' },
    heartbeatWorld: { _type: 'mutation', endpoint: '/town/heartbeat' },
    joinWorld: { _type: 'mutation', endpoint: '/town/join' },
    leaveWorld: { _type: 'mutation', endpoint: '/town/leave' },
    sendWorldInput: { _type: 'mutation', endpoint: '/town/input' },
    previousConversation: { _type: 'query', endpoint: '/town/previous-conversation' },
  },
  messages: {
    listMessages: { _type: 'query', endpoint: '/town/messages' },
    writeMessage: { _type: 'mutation', endpoint: '/town/message' },
  },
  aiTown: {
    main: {
      sendInput: { _type: 'mutation', endpoint: '/town/send-input' },
      inputStatus: { _type: 'query', endpoint: '/town/input-status' },
    },
  },
  music: {
    getBackgroundMusic: { _type: 'query', endpoint: '/town/music' },
  },
  testing: {
    stopAllowed: { _type: 'query', endpoint: '/town/testing/stop-allowed' },
    stop: { _type: 'mutation', endpoint: '/town/testing/stop' },
    resume: { _type: 'mutation', endpoint: '/town/testing/resume' },
  },
};

export const internal = api;
