# Security

This project is a local, single-operator prototype. The server binds to the
loopback interface by default, and model credentials stay in the server
process. Treat imported crew files, SQLite workspaces, logs, screenshots, and
provider responses as private operational data.

Do not include credentials, real crew data, model weights, generated
workspaces, or other private material in an issue, pull request, test fixture,
distribution, or source archive.

If you find a security problem, keep details private and contact the repository
owner through an authenticated private channel. Include the affected version,
the smallest reproducible example that does not contain real data, and the
impact. Do not publish an exploit before the owner has had an opportunity to
review it.

This document does not claim that the prototype is certified for regulated
crew scheduling or production deployment.
