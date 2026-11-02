# 0.3.3 — Supported desktop systems

- Support is limited to Windows 10/11 on x64 computers and Apple silicon (M-series) Macs with macOS 14 or later. Linux, Windows on ARM and Intel Macs are outside the supported scope.
- Setup stops on unsupported hosts before creating an environment or downloading dependencies. Windows ARM detection also checks the native host when Python runs under emulation.
- Installation instructions and CI now cover only the supported desktop systems. Historical release notes describe their original release scope.
- Automatic GPU selection and CPU fallback, the simple browser interface, bundled index and retrieval rules remain unchanged.
- Windows 10 remains a compatibility target pending full acceptance on an actual Windows 10 computer; Windows Server CI is not a substitute for that check.
