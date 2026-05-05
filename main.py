import sys
import os
import json
import base64
import io
import traceback
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QTextEdit, QPushButton, QFileDialog,
    QMessageBox, QDialog, QDialogButtonBox, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSplitter, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage

from PIL import Image

# ========== 核心配置：APP Data + 科目/年级子文件夹 ==========
def get_app_data_path():
    """获取跨平台的APP Data根目录"""
    if os.name == 'nt':  # Windows
        app_data = os.environ.get('APPDATA')
        root_path = os.path.join(app_data, "题库编辑器")
    elif os.name == 'posix':  # macOS/Linux
        home = os.path.expanduser("~")
        if sys.platform == 'darwin':  # macOS
            root_path = os.path.join(home, "Library", "Application Support", "题库编辑器")
        else:  # Linux
            root_path = os.path.join(home, ".config", "题库编辑器")
    else:
        root_path = os.path.join(os.getcwd(), "题库数据")  # 兜底

    os.makedirs(root_path, exist_ok=True)
    return root_path

APP_DATA_ROOT = get_app_data_path()
CONFIG_FILE = os.path.join(APP_DATA_ROOT, "config.json")

# ========== 首次运行配置对话框 ==========
class ConfigDialog(QDialog):
    """首次运行时的科目和年级选择对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("首次运行设置")
        self.setFixedSize(300, 150)
        layout = QVBoxLayout(self)

        # 科目
        subject_layout = QHBoxLayout()
        subject_layout.addWidget(QLabel("科目:"))
        self.subject_combo = QComboBox()
        self.subject_combo.addItems(["数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治"])
        self.subject_combo.setCurrentText("数学")
        subject_layout.addWidget(self.subject_combo)
        layout.addLayout(subject_layout)

        # 年级
        grade_layout = QHBoxLayout()
        grade_layout.addWidget(QLabel("年级:"))
        self.grade_combo = QComboBox()
        self.grade_combo.addItems(["一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
                                   "初一", "初二", "初三", "高一", "高二", "高三"])
        self.grade_combo.setCurrentText("一年级")
        grade_layout.addWidget(self.grade_combo)
        layout.addLayout(grade_layout)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self):
        return self.subject_combo.currentText(), self.grade_combo.currentText()


# ========== 配对编辑表格（修复版） ==========
class PairTableWidget(QTableWidget):
    """用于编辑拖拽配对/连线题的左右项表格"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["左侧项", "右侧项"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # 增强编辑触发器：双击、快捷键、单击选中后再单击编辑
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.EditKeyPressed |
            QAbstractItemView.SelectedClicked
        )
        self.verticalHeader().setVisible(False)

    def set_pairs(self, pairs):
        """设置配对数据，pairs: [{"left":..., "right":...}]"""
        self.clearContents()
        self.setRowCount(len(pairs))
        for row, pair in enumerate(pairs):
            self.setItem(row, 0, QTableWidgetItem(pair.get("left", "")))
            self.setItem(row, 1, QTableWidgetItem(pair.get("right", "")))

    def get_pairs(self):
        """获取当前配对列表"""
        pairs = []
        for row in range(self.rowCount()):
            left_item = self.item(row, 0)
            right_item = self.item(row, 1)
            left = left_item.text().strip() if left_item else ""
            right = right_item.text().strip() if right_item else ""
            if left and right:
                pairs.append({"left": left, "right": right})
        return pairs

    def add_row(self):
        """添加一行空白配对，并确保单元格可编辑"""
        row = self.rowCount()
        self.insertRow(row)
        # 关键修复：为新行的两个单元格创建空item，否则无法编辑
        self.setItem(row, 0, QTableWidgetItem(""))
        self.setItem(row, 1, QTableWidgetItem(""))
        self.scrollToBottom()
        # 可选：自动进入编辑模式（方便连续输入）
        self.editItem(self.item(row, 0))

    def remove_selected_row(self):
        """删除当前选中的行"""
        current_row = self.currentRow()
        if current_row >= 0:
            self.removeRow(current_row)


# ========== 题目列表控件 ==========
class QuestionTableWidget(QTableWidget):
    """显示题目列表的表格"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["序号", "题型", "题目"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.question_data = []   # 存储所有题目字典

    def _check_index(self, index):
        return 0 <= index < len(self.question_data)

    def add_question(self, data):
        """添加题目，返回新题目的索引"""
        if not isinstance(data, dict):
            return -1
        index = len(self.question_data)
        self.question_data.append(data)
        self.insertRow(index)
        self.setItem(index, 0, QTableWidgetItem(str(index + 1)))
        self.setItem(index, 1, QTableWidgetItem(data.get("type", "未知")))
        self.setItem(index, 2, QTableWidgetItem(data.get("question", "")[:50] + "..."))
        return index

    def update_question(self, index, data):
        """更新指定索引的题目"""
        if not self._check_index(index):
            return
        self.question_data[index] = data
        self.setItem(index, 1, QTableWidgetItem(data.get("type", "未知")))
        self.setItem(index, 2, QTableWidgetItem(data.get("question", "")[:50] + "..."))

    def delete_question(self, index):
        """删除指定索引的题目"""
        if not self._check_index(index):
            return
        self.question_data.pop(index)
        self.removeRow(index)
        # 重排后续序号
        for i in range(index, self.rowCount()):
            self.setItem(i, 0, QTableWidgetItem(str(i + 1)))

    def get_selected_index(self):
        """获取当前选中的行索引，未选中返回 -1"""
        current = self.currentRow()
        return current if self._check_index(current) else -1

    def load_from_list(self, questions):
        """从题目列表加载数据（清空现有）"""
        self.setRowCount(0)
        self.question_data = []
        if not isinstance(questions, list):
            QMessageBox.warning(self, "错误", "题库数据格式错误！")
            return

        valid_count = 0
        for q in questions:
            try:
                if not isinstance(q, dict):
                    continue
                # 补全缺失字段（兼容新旧格式）
                q.setdefault("type", "选择题")
                q.setdefault("question", "")
                q.setdefault("answer", "")
                q.setdefault("options", [])
                q.setdefault("pairs", [])
                q.setdefault("image", None)

                self.question_data.append(q)
                self.insertRow(valid_count)
                self.setItem(valid_count, 0, QTableWidgetItem(str(valid_count + 1)))
                self.setItem(valid_count, 1, QTableWidgetItem(q["type"]))
                self.setItem(valid_count, 2, QTableWidgetItem(q["question"][:50] + "..."))
                valid_count += 1
            except Exception:
                continue

        QMessageBox.information(self, "提示", f"加载完成：有效题目 {valid_count} 条")

    def get_all_questions(self):
        return self.question_data.copy()


# ========== 题目编辑面板（支持配对题型） ==========
class QuestionEditPanel(QWidget):
    """右侧题目编辑区（带滚动）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_index = -1
        self.current_image_data = None   # base64 字符串
        self.is_processing = False

        self.init_ui()
        self.setup_connections()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 题型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("题型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["选择题", "填空题", "简答题", "拖拽配对", "连线题"])
        type_layout.addWidget(self.type_combo)
        main_layout.addLayout(type_layout)

        # 题目
        main_layout.addWidget(QLabel("题目:"))
        self.question_text = QTextEdit()
        self.question_text.setMaximumHeight(100)
        main_layout.addWidget(self.question_text)

        # 选项（仅选择题可见）
        self.options_label = QLabel("选项（每行一个）:")
        main_layout.addWidget(self.options_label)
        self.options_text = QTextEdit()
        self.options_text.setMaximumHeight(100)
        main_layout.addWidget(self.options_text)

        # 配对编辑区（拖拽配对/连线题）
        self.pairs_label = QLabel("配对列表（左侧 ↔ 右侧）:")
        main_layout.addWidget(self.pairs_label)
        self.pairs_table = PairTableWidget()
        self.pairs_table.setMinimumHeight(150)
        main_layout.addWidget(self.pairs_table)

        # 配对表格的操作按钮
        pair_btn_layout = QHBoxLayout()
        self.add_pair_btn = QPushButton("添加一行")
        self.remove_pair_btn = QPushButton("删除选中行")
        pair_btn_layout.addWidget(self.add_pair_btn)
        pair_btn_layout.addWidget(self.remove_pair_btn)
        main_layout.addLayout(pair_btn_layout)

        # 答案（普通题型可见）
        main_layout.addWidget(QLabel("答案:"))
        self.answer_text = QTextEdit()
        self.answer_text.setMaximumHeight(100)
        main_layout.addWidget(self.answer_text)

        # 图片
        image_layout = QHBoxLayout()
        image_layout.addWidget(QLabel("图片:"))
        self.select_image_btn = QPushButton("选择图片")
        self.clear_image_btn = QPushButton("清除图片")
        image_layout.addWidget(self.select_image_btn)
        image_layout.addWidget(self.clear_image_btn)
        main_layout.addLayout(image_layout)

        self.image_label = QLabel()
        self.image_label.setFixedSize(150, 150)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.image_label.setScaledContents(False)
        main_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存题目")
        self.delete_btn = QPushButton("删除当前题目")
        self.new_btn = QPushButton("新建题目")
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.new_btn)
        main_layout.addLayout(btn_layout)

        main_layout.addStretch()

        # 初始隐藏配对相关控件
        self.pairs_label.hide()
        self.pairs_table.hide()
        self.add_pair_btn.hide()
        self.remove_pair_btn.hide()
        # 存储答案标签引用以便动态显隐
        self.answer_label = None
        for i in range(main_layout.count()):
            item = main_layout.itemAt(i)
            if item and isinstance(item.widget(), QLabel) and item.widget().text() == "答案:":
                self.answer_label = item.widget()
                break

    def setup_connections(self):
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.select_image_btn.clicked.connect(self.on_select_image)
        self.clear_image_btn.clicked.connect(self.on_clear_image)
        self.save_btn.clicked.connect(self.on_save)
        self.delete_btn.clicked.connect(self.on_delete)
        self.new_btn.clicked.connect(self.on_new)
        self.add_pair_btn.clicked.connect(self.pairs_table.add_row)
        self.remove_pair_btn.clicked.connect(self.pairs_table.remove_selected_row)

    def on_type_changed(self, qtype):
        """题型改变时显示/隐藏对应的编辑控件"""
        is_choice = (qtype == "选择题")
        is_pair_type = (qtype == "拖拽配对" or qtype == "连线题")

        # 选项控件
        self.options_label.setVisible(is_choice)
        self.options_text.setVisible(is_choice)
        # 配对控件
        self.pairs_label.setVisible(is_pair_type)
        self.pairs_table.setVisible(is_pair_type)
        self.add_pair_btn.setVisible(is_pair_type)
        self.remove_pair_btn.setVisible(is_pair_type)
        # 答案控件：配对题型隐藏答案输入框
        self.answer_text.setVisible(not is_pair_type)
        if self.answer_label:
            self.answer_label.setVisible(not is_pair_type)

    def _safe_image_process(self, img_data):
        """使用 PIL 处理图片，返回 QPixmap 和错误信息"""
        try:
            img_bytes = io.BytesIO(img_data)
            img_bytes.seek(0)
            img = Image.open(img_bytes)
            img.verify()
            img_bytes.seek(0)
            img = Image.open(img_bytes)
            # 缩略图
            img.thumbnail((150, 150), Image.Resampling.LANCZOS)
            # 转换为 QPixmap
            if img.mode == "RGB":
                fmt = QImage.Format_RGB888
            elif img.mode == "RGBA":
                fmt = QImage.Format_RGBA8888
            else:
                img = img.convert("RGB")
                fmt = QImage.Format_RGB888
            data = img.tobytes("raw", img.mode)
            qimage = QImage(data, img.width, img.height, fmt)
            pixmap = QPixmap.fromImage(qimage)
            return pixmap, None
        except Exception as e:
            return None, str(e)

    def on_select_image(self):
        if self.is_processing:
            return
        self.is_processing = True
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.tiff);;所有文件 (*.*)"
        )
        if file_path:
            if os.path.getsize(file_path) > 10 * 1024 * 1024:
                QMessageBox.warning(self, "警告", "图片大小不能超过10MB！")
                self.is_processing = False
                return
            try:
                with open(file_path, 'rb') as f:
                    img_data = f.read()
                pixmap, error = self._safe_image_process(img_data)
                if pixmap is not None:
                    self.image_label.setPixmap(pixmap)
                    self.current_image_data = base64.b64encode(img_data).decode('utf-8')
                else:
                    QMessageBox.critical(self, "错误", f"图片加载失败：{error}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"文件读取失败：{str(e)}")
        self.is_processing = False

    def on_clear_image(self):
        self.current_image_data = None
        self.image_label.clear()

    def load_question(self, index, data):
        """加载题目数据到编辑区"""
        try:
            self.current_index = index
            qtype = data.get("type", "选择题")
            question = data.get("question", "")
            answer = data.get("answer", "")
            options = data.get("options", [])
            pairs = data.get("pairs", [])

            self.type_combo.setCurrentText(qtype)
            self.question_text.setPlainText(question)
            self.answer_text.setPlainText(answer)

            if qtype == "选择题":
                self.options_text.setPlainText("\n".join(options))
            else:
                self.options_text.clear()

            # 加载配对数据
            self.pairs_table.set_pairs(pairs)

            # 根据题型显示/隐藏相应控件
            self.on_type_changed(qtype)

            # 清空图片显示
            self.image_label.clear()
            self.current_image_data = None
            image_base64 = data.get("image")
            if image_base64 and isinstance(image_base64, str):
                try:
                    img_data = base64.b64decode(image_base64)
                    pixmap, error = self._safe_image_process(img_data)
                    if pixmap is not None:
                        self.image_label.setPixmap(pixmap)
                        self.current_image_data = image_base64
                    else:
                        QMessageBox.warning(self, "警告", f"题目图片加载失败：{error}")
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"图片解码失败：{str(e)}")
        except Exception as e:
            QMessageBox.warning(self, "警告", f"题目加载失败：{str(e)}")

    def get_current_data(self):
        """从界面获取题目数据字典"""
        qtype = self.type_combo.currentText().strip()
        question = self.question_text.toPlainText().strip()

        if not qtype:
            QMessageBox.warning(self, "提示", "请选择题型！")
            return None
        if not question:
            QMessageBox.warning(self, "提示", "题目内容不能为空！")
            return None

        # 处理配对题型
        if qtype in ("拖拽配对", "连线题"):
            pairs = self.pairs_table.get_pairs()
            if len(pairs) == 0:
                QMessageBox.warning(self, "提示", "请至少添加一对配对项！")
                return None
            # 配对题型的答案字段可留空，答题器不依赖此字段
            return {
                "type": qtype,
                "question": question,
                "answer": "",   # 留空，由配对内容决定
                "options": [],
                "pairs": pairs,
                "image": self.current_image_data
            }

        # 普通题型（选择题、填空题、简答题）
        answer = self.answer_text.toPlainText().strip()
        if not answer:
            QMessageBox.warning(self, "提示", "答案内容不能为空！")
            return None

        options = []
        if qtype == "选择题":
            options_text = self.options_text.toPlainText().strip()
            if not options_text:
                QMessageBox.warning(self, "提示", "选择题必须填写选项！")
                return None
            options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
            if len(options) < 2:
                QMessageBox.warning(self, "提示", "选择题至少需要2个有效选项！")
                return None

        return {
            "type": qtype,
            "question": question,
            "answer": answer,
            "options": options,
            "pairs": [],
            "image": self.current_image_data
        }

    def set_callbacks(self, on_save, on_delete, on_clear_selection):
        """设置回调函数，由主窗口传入"""
        self.save_requested = on_save
        self.delete_requested = on_delete
        self.clear_selection_requested = on_clear_selection

    def on_save(self):
        if self.is_processing:
            return
        self.is_processing = True
        data = self.get_current_data()
        if data is None:
            self.is_processing = False
            return
        self.save_requested(data, self.current_index)
        self.is_processing = False

    def on_delete(self):
        if self.current_index < 0:
            QMessageBox.information(self, "提示", "未选中任何题目，无法删除！")
            return
        reply = QMessageBox.question(self, "确认删除", "确定要删除该题目吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_requested(self.current_index)
            self.clear_fields()
            self.current_index = -1
            self.clear_selection_requested()

    def on_new(self):
        reply = QMessageBox.question(self, "确认新建", "确定要新建题目吗？当前编辑内容会丢失！",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.clear_fields()
            self.current_index = -1
            self.clear_selection_requested()

    def clear_fields(self):
        self.type_combo.setCurrentText("选择题")
        self.question_text.clear()
        self.answer_text.clear()
        self.options_text.clear()
        self.pairs_table.set_pairs([])
        self.on_type_changed("选择题")
        self.current_image_data = None
        self.image_label.clear()


# ========== 主窗口 ==========
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("题库编辑器")
        self.resize(900, 600)

        self.current_file_path = None   # 当前打开的题库文件路径
        self.is_saving = False

        # 加载或选择配置
        self.config = self.load_config_safe()

        # 创建中心控件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 分割器
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧题目列表
        self.question_table = QuestionTableWidget()
        splitter.addWidget(self.question_table)

        # 右侧编辑区（带滚动）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        self.edit_panel = QuestionEditPanel()
        scroll_area.setWidget(self.edit_panel)
        splitter.addWidget(scroll_area)

        splitter.setSizes([300, 600])

        # 设置回调
        self.edit_panel.set_callbacks(
            on_save=self.on_save_question,
            on_delete=self.on_delete_question,
            on_clear_selection=self.clear_list_selection
        )

        # 连接列表选中事件
        self.question_table.itemSelectionChanged.connect(self.on_question_selected)

        # 创建菜单栏
        self.create_menu_bar()

        # 加载默认题库
        self.load_default_questions()

    def load_config_safe(self):
        """安全加载配置，仅首次运行时弹出对话框"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "警告", f"配置文件读取失败：{str(e)}，将使用默认配置（数学-一年级）")
                return {"subject": "数学", "grade": "一年级"}

        # 首次运行，弹出配置对话框
        dlg = ConfigDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            subject, grade = dlg.get_config()
        else:
            subject, grade = "数学", "一年级"
        config = {"subject": subject, "grade": grade}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return config

    def get_subject_grade_path(self):
        """获取科目/年级子文件夹路径，自动创建"""
        subject = self.config.get("subject", "数学")
        grade = self.config.get("grade", "一年级")
        sub_path = os.path.join(APP_DATA_ROOT, subject, grade)
        os.makedirs(sub_path, exist_ok=True)
        return sub_path

    def get_default_question_path(self):
        """默认题库路径"""
        return os.path.join(self.get_subject_grade_path(), "题库.json")

    def load_default_questions(self):
        """加载首次设置的科目/年级文件夹下的默认题库"""
        try:
            default_path = self.get_default_question_path()
            if os.path.exists(default_path):
                with open(default_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                questions = data.get("questions", data) if isinstance(data, dict) else data
                self.question_table.load_from_list(questions)
                self.current_file_path = default_path
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载默认题库失败：{str(e)}，将新建空白题库")

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")

        new_action = file_menu.addAction("新建题库")
        new_action.triggered.connect(self.on_new_question_bank)

        open_action = file_menu.addAction("打开题库")
        open_action.triggered.connect(self.on_open_question_bank)

        save_action = file_menu.addAction("保存题库")
        save_action.triggered.connect(self.on_save_question_bank)

        save_as_action = file_menu.addAction("另存为")
        save_as_action.triggered.connect(self.on_save_as_question_bank)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)

    def clear_list_selection(self):
        self.question_table.clearSelection()

    def on_question_selected(self):
        index = self.question_table.get_selected_index()
        if index >= 0:
            data = self.question_table.question_data[index]
            self.edit_panel.load_question(index, data)

    def on_save_question(self, question_data, index):
        """保存当前编辑的题目到内存，并自动保存题库到文件"""
        if index == -1:
            new_idx = self.question_table.add_question(question_data)
            self.question_table.selectRow(new_idx)
        else:
            self.question_table.update_question(index, question_data)
        # 自动保存整个题库（静默）
        self.auto_save_question_bank()

    def on_delete_question(self, index):
        self.question_table.delete_question(index)
        self.clear_list_selection()
        self.auto_save_question_bank()

    def auto_save_question_bank(self):
        """自动保存题库到当前文件路径或默认路径（静默，不弹出成功提示）"""
        if self.current_file_path:
            self.save_questions_to_file(self.current_file_path, silent=True)
        else:
            default_path = self.get_default_question_path()
            self.save_questions_to_file(default_path, silent=True)

    def save_questions_to_file(self, filename, silent=False):
        """保存题库到文件，silent=True 时不弹出成功消息框"""
        if self.is_saving:
            return
        self.is_saving = True
        try:
            dir_path = os.path.dirname(filename)
            if dir_path and not os.access(dir_path, os.W_OK):
                QMessageBox.critical(self, "错误", "没有该目录的写入权限！")
                return

            save_data = {
                "subject": self.config.get("subject"),
                "grade": self.config.get("grade"),
                "questions": self.question_table.get_all_questions()
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=4)

            self.current_file_path = filename
            if not silent:
                QMessageBox.information(self, "成功", f"保存成功！\n路径：{filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")
        finally:
            self.is_saving = False

    def on_new_question_bank(self):
        if self.question_table.rowCount() > 0:
            reply = QMessageBox.question(self, "确认", "新建将清空所有题目，是否继续？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.question_table.setRowCount(0)
        self.question_table.question_data = []
        self.edit_panel.clear_fields()
        self.current_file_path = None
        self.clear_list_selection()

    def on_open_question_bank(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开题库", "", "JSON文件 (*.json);;所有文件 (*.*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            questions = data.get("questions", data) if isinstance(data, dict) else data
            self.question_table.load_from_list(questions)
            self.edit_panel.clear_fields()
            self.current_file_path = file_path
            self.clear_list_selection()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开失败：{str(e)}")

    def on_save_question_bank(self):
        if self.current_file_path:
            self.save_questions_to_file(self.current_file_path, silent=False)
        else:
            self.save_questions_to_file(self.get_default_question_path(), silent=False)

    def on_save_as_question_bank(self):
        default_dir = self.get_subject_grade_path()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default_dir, "JSON文件 (*.json)"
        )
        if file_path:
            if not file_path.endswith('.json'):
                file_path += '.json'
            self.save_questions_to_file(file_path, silent=False)

    def closeEvent(self, event):
        if self.question_table.rowCount() > 0 and not self.current_file_path:
            reply = QMessageBox.question(self, "确认退出", "题库未保存，是否退出？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()


# ========== 全局异常捕获 ==========
def main():
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        error_log = os.path.join(APP_DATA_ROOT, f"崩溃日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(error_log, 'w', encoding='utf-8') as f:
            f.write(f"错误信息：{str(e)}\n堆栈：{traceback.format_exc()}")
        QMessageBox.critical(None, "致命错误", f"程序异常崩溃！\n错误日志已保存至：{error_log}")


if __name__ == "__main__":
    main()
