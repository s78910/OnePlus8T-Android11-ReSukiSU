#!/bin/bash
set -e

cd $GITHUB_WORKSPACE/device_kernel

echo "=========================================="
echo "0. Fixing Qualcomm scripts/gcc-wrapper.py (Transparent Python 2/3 passthrough)..."
echo "=========================================="
if [ -f scripts/gcc-wrapper.py ]; then
    cat << 'EOF' > scripts/gcc-wrapper.py
#!/usr/bin/env python
import sys
import subprocess
sys.exit(subprocess.call(sys.argv[1:]))
EOF
    chmod +x scripts/gcc-wrapper.py
    echo "[+] scripts/gcc-wrapper.py successfully patched for Python 3"
fi

echo "=========================================="
echo "0b. Fixing modern host GCC -fcommon for scripts/dtc yylloc..."
echo "=========================================="
sed -i 's/^YYLTYPE yylloc;/extern YYLTYPE yylloc;/' scripts/dtc/dtc-lexer.l 2>/dev/null || true
sed -i 's/^YYLTYPE yylloc;/extern YYLTYPE yylloc;/' scripts/dtc/dtc-lexer.lex.c_shipped 2>/dev/null || true
sed -i 's/HOSTCFLAGS   :=/HOSTCFLAGS   := -fcommon /' Makefile
sed -i 's/HOSTCFLAGS\t:=/HOSTCFLAGS\t:= -fcommon /' Makefile

echo "=========================================="
echo "1. Injecting ReSukiSU driver..."
echo "=========================================="
curl -LSs "https://raw.githubusercontent.com/Baka-SU/BakaSU/refs/heads/main/kernel/setup.sh" | bash -s main

echo "=========================================="
echo "2. Applying SuSFS v2 & ReSukiSU integration..."
echo "=========================================="
python3 $GITHUB_WORKSPACE/apply_susfs_fixes.py $GITHUB_WORKSPACE/device_kernel $GITHUB_WORKSPACE/zee295_susfs

echo "=========================================="
echo "2b. Eliminating -dirty from ReSukiSU/BakaSU Driver Version..."
echo "=========================================="
find KernelSU drivers/kernelsu -name "Kbuild" -exec sed -i 's/KSU_COMMIT_SHA)-dirty/KSU_COMMIT_SHA)/g' {} + 2>/dev/null || true
find KernelSU drivers/kernelsu -name "Kbuild" -exec sed -i 's/-dirty//g' {} + 2>/dev/null || true

if [ -d KernelSU/.git ]; then
    (cd KernelSU && git config user.email "ci@local" && git config user.name "CI" && git add -A && git commit -m "clean") || true
fi
if [ -d drivers/kernelsu/.git ]; then
    (cd drivers/kernelsu && git config user.email "ci@local" && git config user.name "CI" && git add -A && git commit -m "clean") || true
fi


echo "=========================================="
echo "3. Spoofing Stock Version to 4.19.110-perf+..."
echo "=========================================="
sed -i 's/^SUBLEVEL =.*/SUBLEVEL = 110/' Makefile
sed -i 's/^EXTRAVERSION =.*/EXTRAVERSION =/' Makefile

# Prevent scripts/setlocalversion from appending -dirty or extra '+'
echo '#!/bin/sh' > scripts/setlocalversion
echo 'echo "-perf+"' >> scripts/setlocalversion
chmod +x scripts/setlocalversion
touch .scmversion

echo "=========================================="
echo "4. Applying OnePlus Golden stock_config, Manual Hook & SuSFS flags..."
echo "=========================================="
cp $GITHUB_WORKSPACE/stock_config arch/arm64/configs/stock_defconfig
DEFCONFIG="arch/arm64/configs/stock_defconfig"

# Disable problematic BTF debugging
sed -i 's/CONFIG_DEBUG_INFO_BTF=y/# CONFIG_DEBUG_INFO_BTF is not set/g' $DEFCONFIG
echo "CONFIG_DEBUG_INFO_BTF=n" >> $DEFCONFIG

# Disable module signature enforcement so prebuilt vendor .ko modules load without signature rejection
sed -i 's/CONFIG_MODULE_SIG=y/# CONFIG_MODULE_SIG is not set/g' $DEFCONFIG
sed -i 's/CONFIG_MODULE_SIG_FORCE=y/# CONFIG_MODULE_SIG_FORCE is not set/g' $DEFCONFIG
sed -i 's/CONFIG_MODULE_SIG_ALL=y/# CONFIG_MODULE_SIG_ALL is not set/g' $DEFCONFIG
sed -i '/CONFIG_MODULE_SIG_KEY/d' $DEFCONFIG
sed -i '/CONFIG_MODULE_FORCE_LOAD/d' $DEFCONFIG
echo "CONFIG_MODULE_FORCE_LOAD=y" >> $DEFCONFIG

# Ensure exact localversion
sed -i '/CONFIG_LOCALVERSION/d' $DEFCONFIG
echo 'CONFIG_LOCALVERSION="-perf+"' >> $DEFCONFIG
echo 'CONFIG_LOCALVERSION_AUTO=n' >> $DEFCONFIG

# Enable KSU & Manual Hook flags
echo "CONFIG_KSU=y" >> $DEFCONFIG
echo "CONFIG_KSU_MANUAL_HOOK=y" >> $DEFCONFIG
echo "CONFIG_KSU_MANUAL_HOOK_AUTO_SETUID_HOOK=y" >> $DEFCONFIG
echo "CONFIG_KSU_MANUAL_HOOK_AUTO_INITRC_HOOK=y" >> $DEFCONFIG
echo "CONFIG_KSU_MANUAL_HOOK_AUTO_INPUT_HOOK=y" >> $DEFCONFIG
echo "CONFIG_KALLSYMS=y" >> $DEFCONFIG
echo "CONFIG_KALLSYMS_ALL=y" >> $DEFCONFIG

# Enable SuSFS flags
echo "CONFIG_KSU_SUSFS=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SUS_PATH=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SUS_MOUNT=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SUS_KSTAT=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SPOOF_UNAME=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_ENABLE_LOG=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_OPEN_REDIRECT=y" >> $DEFCONFIG
echo "CONFIG_KSU_SUSFS_SUS_MAP=y" >> $DEFCONFIG

# Also update vendor/kona-perf_defconfig as backup
cp arch/arm64/configs/stock_defconfig arch/arm64/configs/vendor/kona-perf_defconfig

echo "=========================================="
echo "5. Bypassing vendor module CRC & signature checks in kernel/module.c..."
echo "=========================================="
python3 $GITHUB_WORKSPACE/patch_module_compat.py $GITHUB_WORKSPACE/device_kernel

echo "[+] patch_kernel.sh completed successfully!"


