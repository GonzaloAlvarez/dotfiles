
# Node-based CLIs (qwen-code; npm installs of Claude Code on Node < 22.15) do
# not read the OS trust store, so on the LAN they reject homelab step-ca
# leaves such as https://llmrouter.lab.gn.al. Point Node at the root that
# amun's pki role installs. macOS keeps it in the System keychain instead of
# a file: export it once with
#   security find-certificate -c cn-pki-root -p > ~/.config/cn-pki/root_ca.crt
if [ -r /usr/local/share/ca-certificates/cn-pki-root.crt ]; then
    export NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/cn-pki-root.crt
elif [ -r /etc/ca-certificates/trust-source/anchors/cn-pki-root.crt ]; then
    export NODE_EXTRA_CA_CERTS=/etc/ca-certificates/trust-source/anchors/cn-pki-root.crt
elif [ -r "$HOME/.config/cn-pki/root_ca.crt" ]; then
    export NODE_EXTRA_CA_CERTS="$HOME/.config/cn-pki/root_ca.crt"
fi
