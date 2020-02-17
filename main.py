import numpy as np
from PyQt5 import uic
from PyQt5.QtWidgets import *
import sys
from vispy import scene, color
import vispy.scene
from custom_util import prompt_saving, floodfill, crop_reserve, crop_remove, FloodfillError, Scene
from models import Segment
import os
import open3d as o3d
import copy


class AtlasAnnotationTool(QWidget):
    def __init__(self, app):
        super(AtlasAnnotationTool, self).__init__()
        base_form, window = uic.loadUiType("main.ui")
        self.window = window()
        self.base_form = base_form()
        self.base_form.setupUi(self.window)

        # bookkeeping variable
        self.data_fname = "segments.json"
        self.point_size = 3.5
        self.message = "> Program Started, UI Loaded"
        self.selected_points_id = []
        self.largest_seg_id = -1
        self.segmentations = [] # list of segmentations of type Segmentation

        self.current_data_file_name = None
        self.current_result_point_indices = []

        # scene variables -- common
        self.upperScene = Scene()
        self.lowerScene = Scene()
        self.message_center = None
        self.segmentation_list = None
        self.btn_common_save = None
        self.btn_common_load = None
        self.btn_common_delete = None

        # scene variable -- floodfill specific buttons
        self.btn_floodfill_done = None
        self.btn_floodfill_cancel = None

        # setup
        self.setUpDisplay()
        self.wireWidgets()
        self.setOnClickListener()
        self.populateSegmentList()

        # color field for point cloud
        self.load = False
        self.cmap = color.get_colormap('viridis')
        self.upperColor = None
        self.lowerColor = None
        self.upperCurColor = None

        # Demo
        # self.addSegmentationItems(["Placeholder 1", "Placeholder 2"])
        # pcd = o3d.io.read_point_cloud("./data/scene.ply")
        # self.upperScene.render(pcd)
        self.window.show()
        app.exec_()

    ####### SET UP FUNCTIONS #######
    def setOnClickListener(self):
        self.btn_floodfill_done.clicked.connect(self.btn_floodfill_done_clicked)
        self.btn_floodfill_cancel.clicked.connect(self.btn_floodfill_cancel_clicked)
        self.upperScene.canvas.events.mouse_release.connect(self.topCanvasClicked)
        self.btn_common_load.clicked.connect(self.btn_common_load_clicked)
        self.btn_common_save.clicked.connect(self.btn_save_clicked)
        self.btn_common_delete.clicked.connect(self.btn_delete_clicked)
        self.segmentation_list.itemDoubleClicked.connect(self.segmentation_list_item_double_clicked)


    def wireWidgets(self):
        # scene wiring
        self.base_form.data_display_window.addWidget(self.upperScene.canvas.native)
        self.base_form.data_display_window.addWidget(self.lowerScene.canvas.native)

        # message box wiring
        self.message_center = self.base_form.message_center_layout.itemAt(0).widget()

        # segmentation list wiring
        self.segmentation_list = self.base_form.segmentation_layout.itemAt(0).widget()
        # scene button wiring
        self.btn_common_save = self.base_form.common_buttons_layout.itemAt(0).widget()
        self.btn_common_load = self.base_form.common_buttons_layout.itemAt(1).widget()
        self.btn_common_delete = self.base_form.common_buttons_layout.itemAt(2).widget()

        # Floodfill wiring
        tab_floodfill = self.base_form.system_mode_layout.itemAt(0).widget()
        self.btn_floodfill_done = tab_floodfill.widget(0).children()[1]
        self.btn_floodfill_cancel = tab_floodfill.widget(0).children()[2]


    def setUpDisplay(self):
        self.upperScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)
        self.lowerScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)

    ####### ON CLICK FUNCTIONS #######
    def segmentation_list_item_double_clicked(self):
        '''
        When an item is double clicked, read that file and render it onto the upper scene
        '''
        current_item_text = self.segmentation_list.currentItem().text()
        try:
            current_item_index = int(current_item_text.split(" | ")[0])
            current_segmentation = self.segmentations[current_item_index]
            index_to_highlight = current_segmentation.indices
            fname = str(current_segmentation.data_file_name)

            pcd = o3d.io.read_point_cloud(fname)
            class DataPCDIsEmptyException(Exception):
                pass
            if pcd.is_empty():
                raise DataPCDIsEmptyException("ERR: Data file at {} is cannot be found or is empty".format(fname))

            self.upperScene.render(pcd)
        except ValueError as e:
            self.writeMessage("ERR: Index is not an int --> {}".format(current_item_text.split(" | ")[0]))

    def btn_common_load_clicked(self):
        '''
        When load is clicked, load the file and render it onto the upper scene
        '''
        filename = self.openFileNamesDialog()
        # do filetype checking here
        if filename:
            self.current_data_file_name = filename
            self.writeMessage("Opening file <{}>".format(filename))
            self.upperScene.render(o3d.io.read_point_cloud(filename))
            self.renderScene(self.upperScene, findColor=True)   # change color for upperScene
            self.load = True

    def btn_floodfill_done_clicked(self):
        '''
        When the floodfill button is clicked
        1. get the selected points
        2. get the surface that needs to be cropped
        3. render the result in the lower scene
        '''
        try:
            surface_to_crop = floodfill(self.selected_points_id, self.upperScene.pcd)
            self.current_result_point_indices = surface_to_crop
            new_pcd = crop_reserve(self.upperScene.pcd, surface_to_crop)
            self.lowerScene.render(new_pcd)
            self.renderScene(self.lowerScene, findColor=True)   # change color for lowerScene
        except Exception as e:
            self.writeMessage(str(e))
        if self.load: self.renderScene(self.upperScene)   # clean upperScene
        self.writeMessage("Selected Points is cleared")
        self.selected_points_id = []

    def btn_floodfill_cancel_clicked(self):
        '''
        When cancel is clicked
        1. clear all selected points
        2. clear the lower scene
        '''
        self.writeMessage("Selected Segmentation Cancelled".format(len(self.selected_points_id)))
        self.selected_points_id = []
        if self.load: self.renderScene(self.upperScene)   # clean upperScene
        self.current_result_point_indices = []
        self.lowerScene.clear()

    def btn_delete_clicked(self):
        print("NOT IMPLEMENTED YET")

    def btn_save_clicked(self):
        '''
        When save is clicked
        1. Prompt the user for the name and type of the object
        2. save the object

        '''
        data = prompt_saving()
        if len(self.current_result_point_indices) == 0:
            self.writeMessage("There are no points to save")
        else:
            import json
            a = []
            if not os.path.isfile(self.data_fname):
                self.largest_seg_id = self.largest_seg_id + 1
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                a.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(a, indent=2))
            else:
                with open(self.data_fname) as feedsjson:
                    feeds = json.load(feedsjson)
                self.largest_seg_id = len(feeds)
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                feeds.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(feeds, indent=2))
            self.lowerScene.clear()

    def topCanvasClicked(self, event):
        '''
        When the top canvas is clicked
        1. rotate the scene if necessary
        2. record the point clicked if necessary
        3. show the points clicked (STILL NEED TO IMPLEMENT)
        :param event: event that the top canvas is clicked.
        :return:
        '''
        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        # set pos and color
        kwargs = dict(symbol='o', size=self.point_size, edge_color=None)
        # prepare list of unique colors needed for picking
        ids = np.arange(1, len(points) + 1, dtype=np.uint32).view(np.uint8)
        ids = ids.reshape(-1, 4)
        ids = np.divide(ids, 255, dtype=np.float32)
        # connect events
        if event.button == 1 and self.distance_traveled(event.trail()) <= 2:
            pos = self.upperScene.canvas.transforms.canvas_transform.map(event.pos)
            try:
                self.upperScene.marker.update_gl_state(blend=False)
                self.upperScene.marker.antialias = 0
                self.upperScene.marker.set_data(points, face_color=ids, **kwargs)
                img = self.upperScene.canvas.render((pos[0] - 2,
                                                     pos[1] - 2,
                                                     2 * 10 + 1,
                                                     2 * 10 + 1), 
                                                     bgcolor=(0,0,0,0))
            finally:
                self.upperScene.marker.update_gl_state(blend=True)
                self.upperScene.marker.antialias = 1
                self.upperScene.marker.set_data(points, face_color=self.upperCurColor, **kwargs)
            # We pick the pixel directly under the click, unless it is
            # zero, in which case we look for the most common nonzero
            # pixel value in a square region centered on the click.
            idxs = img.ravel().view(np.uint32)
            idx = idxs[len(idxs) // 2]

            if idx == 0:
                idxs, counts = np.unique(idxs, return_counts=True)
                idxs = idxs[np.argsort(counts)]
                idx = idxs[-1] or (len(idxs) > 1 and idxs[-2])
            # call the callback function
            if idx > 0:
                try:
                    points[idx]
                    self.selected_points_id.append(idx)  # TODO how to you not add a point if it is index out of range
                    self.writeMessage("Selected Points {}".format(self.selected_points_id))
                    # turn the on_click point white
                    self.upperCurColor[idx - 1] =  (1, 1, 1, 1)
                    self.upperScene.marker.set_data(points, face_color=self.upperCurColor, **kwargs)
                except IndexError:
                    self.writeMessage("The point {} is not in the point cloud".format(idx))

    # helper function: render scene for a better visulization for on click point
    def renderScene(self, scene, findColor=False):
        if scene is self.upperScene:
            if findColor:
                self.upperColor = self.findColor(self.upperScene)
            self.upperCurColor = copy.deepcopy(self.upperColor)  # if upperScene, reset using_colors
            points = np.asarray(self.upperScene.pcd.points)
            render_color = self.upperColor
        else:
            if findColor:
                self.lowerColor = self.findColor(self.lowerScene)
            points = np.asarray(self.lowerScene.pcd.points)
            render_color = self.lowerColor
        scene.marker.set_gl_state('translucent', blend=True, depth_test=True)
        scene.marker.set_data(points, face_color=render_color, symbol='o', size=self.point_size, edge_color=None)

    # helper function: find suitable color of a scene
    def findColor(self, scene):
        points = np.asarray(scene.pcd.points)
        return np.concatenate(list(map(self.cmap.map, np.linspace(0, 1, len(points)))))


    ####### UTILITIES FUNCTIONS #######

    def openFileNamesDialog(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        files, _ = QFileDialog.getOpenFileNames(self, "QFileDialog.getOpenFileNames()", "",
                                                "All Files (*);;Python Files (*.py)", options=options)
        if files:
            return files[0]
        return None

    @staticmethod
    def distance_traveled(positions):
        """
        Return the total amount of pixels traveled in a sequence of pixel
        `positions`, using Manhattan distances for simplicity.
        """
        return np.sum(np.abs(np.diff(positions, axis=0)))

    def addSegmentationItem(self, segment):
        self.segmentations.append(segment)
        self.segmentation_list.addItem("{} | {} | {}".format(segment.id, segment.segment_name, segment.type_class))

    def writeMessage(self, message):
        '''
        Iteratively populate message
        :param message: new message given
        '''
        self.message = "{} \n> {}".format(self.message, message)  # format the text so that it is one per line
        self.message_center.setPlainText(self.message)  # no url displaying
        self.message_center.verticalScrollBar().setValue(
            self.message_center.verticalScrollBar().maximum())  # scroll bar to the bottom by default

    def populateSegmentList(self):
        '''
        On start, populate a list of segmentations that user previously did
        '''
        try:
            import json
            with open(self.data_fname, 'r') as f:
                segmentations = json.load(f)
            for segment in segmentations:
                segment_dict = json.loads(segment)
                seg = Segment(**segment_dict)
                self.addSegmentationItem(seg)
        except FileNotFoundError as e:
            self.writeMessage("No segmentations detected")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    annotation_tool = AtlasAnnotationTool(app)
