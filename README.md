# relay-agent

Client de [Relay](https://github.com/jStrider/relay) pour un agent IA : il tire les données Santé que l'app a déposées chiffrées sur le relais, les déchiffre avec la phrase d'appairage et les écrit en fichiers ; il planifie les séances de course qui partent sur la montre ; il demande un rafraîchissement ; il sert un pont sans secret à un agent en bac à sable et un serveur MCP.

```sh
pip install relay-agent
export RELAY_PHRASE='relay1:…'      # ou ~/.config/relay/phrase en mode 600
relay-agent sync --dest /workspace
```
