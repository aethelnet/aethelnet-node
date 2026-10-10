# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private reporting instead: **Security → Report a vulnerability** on this repository.
You'll get an answer within a few days. Once a fix is released, we're happy to credit you.

## Running a node safely

- Always set `AETHELNET_AUTH_TOKEN` on nodes reachable from the network. Without it, write requests
  are only accepted from localhost.
- Restrict `AETHELNET_CORS_ORIGINS` to your dashboard's origin.
- Keep `AETHELNET_ALLOW_CODE_EXEC` off unless the node is private and only you can write to it.
  Node content can arrive through the API, vault sync and P2P gossip.
- Set `AETHELNET_PEER_TOKEN` if your peers should be the only ones allowed to gossip with your node.
- Keep wallet keys and API keys in `.env` or a secret manager, never in the repository.
