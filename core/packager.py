"""
ShadowBot 应用打包与代码处理模块
"""
import os
import shutil
import hashlib
import json
import zipfile
import py_compile
import tempfile
import base64
import uuid
from typing import Tuple, Dict, Any, Optional

# === 补丁：让元素库随包走 =====================================================
# 原版 build_app_package 只复制 xbot_robot/，兄弟目录 xbot_selectors/ 从不参与，
# 于是收件方拿到的应用没有元素实体（元素短板）。下面三个开关可用环境变量覆盖：
#   XBOT_INCLUDE_ELEMENTS=0|1       是否把 xbot_selectors/ 打进 package.bot（默认 1）
#   XBOT_ELEMENTS_LAYOUT=root|wrap  打包布局：root=与流程文件同级（默认）；wrap=包根放 xbot_robot/
#   XBOT_ELEMENT_STATUS=0|1         注册时 elementLibraryStatus 取值（默认 1，含义未验证）
INCLUDE_ELEMENTS = os.environ.get("XBOT_INCLUDE_ELEMENTS", "1") != "0"
ELEMENTS_LAYOUT = os.environ.get("XBOT_ELEMENTS_LAYOUT", "root").lower()
ELEMENT_STATUS = int(os.environ.get("XBOT_ELEMENT_STATUS", "1") or 0)


def _collect_element_codes(selectors_dir, pkg_data):
    """元素组 code 集合 = 磁盘上的 element_* 目录 ∪ package.json 的 selectordependencies。"""
    codes = set()
    if selectors_dir and os.path.isdir(selectors_dir):
        for name in os.listdir(selectors_dir):
            if name.startswith("element_"):
                codes.add(name)
    for item in (pkg_data.get("selectordependencies") or []):
        if isinstance(item, str) and item.startswith("element_"):
            codes.add(item)
    return sorted(codes)


AES_FLOW_KEY = base64.b64decode("pO22DRcoQiho/omL8plzGQ==")
AES_FLOW_IV = b"keosmnvbhdueyr2b"


def decrypt_flow_data(raw_data: bytes) -> Tuple[Optional[dict], bool]:
    """
    解密影刀 flow.json 流程定义（支持明文与 AES-CBC 密文）
    """
    raw_strip = raw_data.strip()
    if raw_strip.startswith(b"{"):
        try:
            return json.loads(raw_strip.decode("utf-8")), False
        except Exception:
            return None, False
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        ciphertext = base64.b64decode(raw_strip)
        cipher = AES.new(AES_FLOW_KEY, AES.MODE_CBC, AES_FLOW_IV)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return json.loads(decrypted.decode("utf-8")), True
    except Exception:
        return None, False


def encrypt_flow_data(flow_dict: dict) -> bytes:
    """
    加密影刀 flow.json 流程定义
    """
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    json_str = json.dumps(flow_dict, ensure_ascii=False, indent=2)
    raw = json_str.encode("utf-8")
    cipher = AES.new(AES_FLOW_KEY, AES.MODE_CBC, AES_FLOW_IV)
    ciphertext = cipher.encrypt(pad(raw, AES.block_size))
    return base64.b64encode(ciphertext)


def repair_flow_block_displays(stage_dir: str, pkg_data: Dict[str, Any]):
    """
    遍历 .dev 目录下的所有 *.flow.json 文件，
    将所有调用子流程 (process.run) 积木块中的 inputs.process.display
    自动对齐修正为 package.json 中对应的真实流程名（如 'z 终止流程'），
    解决迁移后调用流程积木块显示底层文件名（如 'process5'）的问题。
    """
    dev_dir = os.path.join(stage_dir, ".dev")
    if not os.path.exists(dev_dir):
        return

    flows = pkg_data.get("flows", [])
    if not flows:
        return

    # 建立 internal_filename -> flow_name 映射
    flow_map = {}
    for fl in flows:
        fn = fl.get("filename")
        nm = fl.get("name")
        if fn and nm:
            flow_map[fn] = nm

    if not flow_map:
        return

    for fname in os.listdir(dev_dir):
        if not fname.endswith(".flow.json"):
            continue
        fpath = os.path.join(dev_dir, fname)
        try:
            raw_data = open(fpath, "rb").read()
            flow_json, was_encrypted = decrypt_flow_data(raw_data)
            if not flow_json or "blocks" not in flow_json:
                continue

            modified = False
            for block in flow_json.get("blocks", []):
                if block.get("name") == "process.run":
                    proc_input = block.get("inputs", {}).get("process", {})
                    val = proc_input.get("value")
                    if val:
                        target_fn = val.split(":", 1)[-1] if ":" in val else val
                        if target_fn in flow_map:
                            expected_name = flow_map[target_fn]
                            if proc_input.get("display") != expected_name:
                                proc_input["display"] = expected_name
                                modified = True

            if modified:
                if was_encrypted:
                    new_data = encrypt_flow_data(flow_json)
                else:
                    new_data = json.dumps(flow_json, ensure_ascii=False, indent=2).encode("utf-8")
                with open(fpath, "wb") as f:
                    f.write(new_data)
        except Exception:
            pass


def calculate_md5(file_path: str) -> str:
    """计算文件的 MD5 摘要 (小写 32 位 hex)"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def compile_py_to_pyc(src_py: str, dst_pyc: str) -> bool:
    """编译单个 Python 源码文件为 .pyc 字节码"""
    py_compile.compile(src_py, cfile=dst_pyc, doraise=True)
    return True


def build_app_package(
    robot_dir: str,
    new_app_name: Optional[str] = None,
    new_uuid: Optional[str] = None,
    encrypt_python: bool = False,
    output_dir: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any], str]:
    """
    打包影刀应用为标准 package.bot 结构并生成 package.json

    :param robot_dir: 原始应用的 xbot_robot 目录
    :param new_app_name: 迁移后的新应用名称 (若为空则保持原名)
    :param new_uuid: 迁移后的新应用 UUID (若为空则生成全新 UUID)
    :param encrypt_python: 是否将 Python 代码编译为字节码以保护源码
    :param output_dir: zip 文件输出路径 (若为空则使用临时目录)
    :return: (zip_file_path, package_md5, updated_package_json, pkg_file_path)
    """
    if not os.path.exists(robot_dir):
        raise FileNotFoundError(f"应用目录不存在: {robot_dir}")

    # 创建临时工作区
    work_temp_dir = tempfile.mkdtemp(prefix="xbot_pack_")
    stage_dir = os.path.join(work_temp_dir, "xbot_robot")

    try:
        # 复制所有文件到工作区，忽略 __pycache__、.git 等（注意：保留 .dev 目录，影刀所有流程积木块 *.flow.json 均存储于 .dev 中）
        def ignore_patterns(path, names):
            ignored = set()
            for n in names:
                if n in [".git", ".svn", "__pycache__", ".vscode", ".idea", "venv", "venv310"]:
                    ignored.add(n)
                elif n.endswith(".pyc") and not encrypt_python:
                    ignored.add(n)
            return ignored

        shutil.copytree(robot_dir, stage_dir, ignore=ignore_patterns)

        # 读取并更新 package.json
        pkg_file = os.path.join(stage_dir, "package.json")
        pkg_data = {}
        if os.path.exists(pkg_file):
            with open(pkg_file, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)

        if new_app_name:
            pkg_data["name"] = new_app_name

        if new_uuid:
            pkg_data["uuid"] = new_uuid

        pkg_data["version"] = "1"

        if pkg_data.get("robot_type") == "activity":
            if not pkg_data.get("activity_code"):
                pkg_data["activity_code"] = f"activity_{uuid.uuid4().hex[:8]}"
            pkg_data["package_code"] = pkg_data["activity_code"]

        if encrypt_python:
            pkg_data["encrypt_bot"] = True

            # 遍历 stage_dir 中的所有 .py 文件编译为 .pyc 并删除源 .py
            for root, _, files in os.walk(stage_dir):
                for f in files:
                    if f.endswith(".py") and f != "__init__.py":
                        py_path = os.path.join(root, f)
                        pyc_path = os.path.join(root, f[:-3] + ".pyc")
                        if compile_py_to_pyc(py_path, pyc_path):
                            os.remove(py_path)

        # 写回 package.json
        with open(pkg_file, "w", encoding="utf-8") as f:
            json.dump(pkg_data, f, ensure_ascii=False, indent=2)

        # === 补丁：把元素库（xbot_selectors/）也纳入本次打包 ===
        selectors_dir = None
        if INCLUDE_ELEMENTS:
            selectors_dir = os.path.join(os.path.dirname(os.path.abspath(robot_dir)), "xbot_selectors")
            if not os.path.isdir(selectors_dir):
                # 兼容：robot_dir 本身就是应用根目录（少数调用方）
                cand = os.path.join(os.path.abspath(robot_dir), "xbot_selectors")
                selectors_dir = cand if os.path.isdir(cand) else None
            element_codes = _collect_element_codes(selectors_dir, pkg_data)
            if element_codes:
                pkg_data["selectordependencies"] = element_codes
                with open(pkg_file, "w", encoding="utf-8") as f:
                    json.dump(pkg_data, f, ensure_ascii=False, indent=2)
                print("[elements] 元素组 %d 个：%s" % (len(element_codes), ", ".join(element_codes)))
            else:
                print("[elements] 未发现元素库（跳过）")

        # 修复 .dev/*.flow.json 中所有调用流程积木块的显示名称
        repair_flow_block_displays(stage_dir, pkg_data)

        # 确定 zip 输出路径
        if not output_dir:
            out_target_dir = tempfile.mkdtemp(prefix="xbot_out_")
        else:
            out_target_dir = output_dir
            os.makedirs(out_target_dir, exist_ok=True)

        zip_path = os.path.join(out_target_dir, "package.bot")
        if os.path.exists(zip_path):
            os.remove(zip_path)

        out_json_path = os.path.join(out_target_dir, "package.json")
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(pkg_data, f, ensure_ascii=False, indent=2)

        # 打包 stage_dir 内的所有内容 (顶层即为 package.json、main.py 等)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(stage_dir):
                for f in files:
                    full_fp = os.path.join(root, f)
                    rel_fp = os.path.relpath(full_fp, stage_dir)
                    if ELEMENTS_LAYOUT == "wrap":
                        rel_fp = os.path.join("xbot_robot", rel_fp)
                    zf.write(full_fp, arcname=rel_fp)
            # === 补丁：元素库放进同一个 package.bot ===
            if selectors_dir:
                n = 0
                for root, dirs, files in os.walk(selectors_dir):
                    for f in files:
                        full_fp = os.path.join(root, f)
                        inner = os.path.relpath(full_fp, selectors_dir)
                        zf.write(full_fp, arcname=os.path.join("xbot_selectors", inner))
                        n += 1
                print("[elements] 已写入 xbot_selectors/：%d 个文件（layout=%s）" % (n, ELEMENTS_LAYOUT))

        # 计算 MD5
        pkg_md5 = calculate_md5(zip_path)

        return zip_path, pkg_md5, pkg_data, out_json_path

    finally:
        # 清理中间构建临时目录
        shutil.rmtree(work_temp_dir, ignore_errors=True)
