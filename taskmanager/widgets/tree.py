"""Tree/list helpers that keep selection and scrolling stable across refreshes."""

from ..qt import QtGui, QtWidgets, Qt

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
KEY_ROLE = Qt.ItemDataRole.UserRole + 2


class SortItem(QtWidgets.QTreeWidgetItem):
    """Item that sorts by the value stored in ``SORT_ROLE`` when present.

    ``rank`` pins an item to a fixed position regardless of the sort column and
    direction; Windows 8 uses it for the *Apps* / *Background processes* group
    headers.
    """

    rank = None

    def __lt__(self, other):
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        if self.rank is not None and getattr(other, "rank", None) is not None:
            ascending = tree is None or tree.header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            return (self.rank < other.rank) if ascending else (self.rank > other.rank)
        mine = self.data(column, SORT_ROLE)
        theirs = other.data(column, SORT_ROLE)
        if mine is None:
            mine = self.text(column).lower()
        if theirs is None:
            theirs = other.text(column).lower()
        try:
            return mine < theirs
        except TypeError:
            return str(mine) < str(theirs)


def set_cell(item, column, text, sort=None, align=None):
    if item.text(column) != text:
        item.setText(column, text)
    if sort is not None and item.data(column, SORT_ROLE) != sort:
        item.setData(column, SORT_ROLE, sort)
    if align is not None:
        item.setTextAlignment(column, align)


RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class ItemSync:
    """Diff-based population of a ``QTreeWidget`` (or of one parent item)."""

    def __init__(self, tree, parent=None, factory=SortItem):
        self.tree = tree
        self.parent = parent
        self.factory = factory
        self.items = {}

    def begin(self):
        self._seen = set()

    def get(self, key):
        self._seen.add(key)
        item = self.items.get(key)
        if item is None:
            item = self.factory()
            item.setData(0, KEY_ROLE, key)
            if self.parent is None:
                self.tree.addTopLevelItem(item)
            else:
                self.parent.addChild(item)
            self.items[key] = item
        return item

    def end(self):
        for key in [k for k in self.items if k not in self._seen]:
            item = self.items.pop(key)
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
            else:
                idx = self.tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)


def make_tree(headers, root_decorated=False):
    tree = QtWidgets.QTreeWidget()
    tree.setColumnCount(len(headers))
    tree.setHeaderLabels(headers)
    tree.setRootIsDecorated(root_decorated)
    tree.setUniformRowHeights(True)
    tree.setSortingEnabled(True)
    tree.setAllColumnsShowFocus(True)
    tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tree.header().setSectionsMovable(True)
    tree.header().setStretchLastSection(True)
    return tree


def selected_key(tree):
    items = tree.selectedItems()
    return items[0].data(0, KEY_ROLE) if items else None


def resort(tree):
    tree.sortItems(tree.sortColumn(), tree.header().sortIndicatorOrder())


def blend(c1, c2, t):
    a, b = QtGui.QColor(c1), QtGui.QColor(c2)
    t = max(0.0, min(1.0, t))
    return QtGui.QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class ColumnChooser(QtWidgets.QDialog):
    """Windows 7 *Select Process Page Columns* dialog."""

    def __init__(self, title, text, columns, visible, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list = QtWidgets.QListWidget()
        for name in columns:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in visible else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(320, 380)

    def chosen(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
