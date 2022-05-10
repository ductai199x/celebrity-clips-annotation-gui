import os
import cv2
import re
import decord
import pandas as pd
import threading
import PySimpleGUI as sg
from PIL import Image, ImageTk

VIDEO_EXTS = "mp4"
FRAME_DISPLAY_SIZE = (480, 270)
SAMPLE_EVERY_N_FRAME = 3
MAX_N_FRAMES_IN_BUFFER = 500


def get_all_files(path, prefix="", suffix="", contains=("",), excludes=("",)):
    if not os.path.isdir(path):
        raise ValueError(f"{path} is not a valid directory.")
    files = []
    for pre, dirs, basenames in os.walk(path):
        for name in basenames:
            if name.startswith(prefix) and name.endswith(suffix) and any([c in name for c in contains]):
                if excludes == ("",):
                    files.append(os.path.join(pre, name))
                else:
                    if all([e not in name for e in excludes]):
                        files.append(os.path.join(pre, name))
    return files


class ClipAnnotationGUI:
    def __init__(self):
        self.layout = [
            [
                sg.Frame(
                    "File Browser",
                    self.file_browser,
                    element_justification="c",
                    key="-FILE_BROWSE_COL-",
                    pad=(10, 10),
                ),
                sg.Frame(
                    "Video Examiner",
                    self.video_examiner,
                    element_justification="c",
                    key="-VIDEO_COL-",
                    pad=(10, 10),
                    expand_y=True,
                ),
            ],
            [sg.HSeparator()],
            [
                sg.Frame(
                    "Annotations",
                    self.annotating_ui,
                    element_justification="c",
                    key="-ANNOTATION_COL-",
                    pad=(10, 10),
                    expand_x=True,
                )
            ],
        ]

        self.window = sg.Window(
            "Clip Annotation Tools",
            self.layout,
            element_justification="center",
            use_default_focus=True,
            finalize=True,
            resizable=True,
        )

        self.full_file_list = []
        self.video_cap = None
        self.video_res = None
        self.video_yt_id = None
        self.video_frame_range = None
        self.video_buffer = None
        self.video_buffer_idx = None
        self.annotation_file = None
        self.annokey_to_elmkey = {
            "file_name": "-ANNO_FILE_NAME-",
            "celeb_name": "-ANNO_CELEB_NAME-",
            "youtube_id": "-ANNO_YT_ID-",
            "frame_range": "-ANNO_FRAME_RANGE-",
            "res_w": "-ANNO_RES_W-",
            "res_h": "-ANNO_RES_H-",
            "is_watermarked": "-ANNO_WATERMARK-",
            "is_pristine": "-ANNO_PRISTINE-",
            "chop_begin": "-ANNO_CHOP_BEGIN-",
            "chop_end": "-ANNO_CHOP_END-",
        }
        self.video_annotations = None

    def run(self):
        while True:
            try:
                pass
            except KeyboardInterrupt:
                break

            # run with a timeout so that current location can be updated
            self.event, self.values = self.window.read(timeout=50)
            if self.event == sg.WIN_CLOSED:
                break

            if self.event == "-FOLDER_LOCATION-":
                try:
                    file_list = get_all_files(self.values["-FOLDER_LOCATION-"], suffix=VIDEO_EXTS)
                except Exception as E:
                    print(f"** Error {E} **")
                    file_list = []
                self.full_file_list = file_list
                self.window["-FILE_LIST-"].update(self.full_file_list)

            elif self.event == "-FILTER_FILE_LIST-" or self.event == "-FILTER_FILE_LIST_BTN-":
                filter_str = self.values["-FILTER_FILE_LIST-"]
                if filter_str is None:
                    filter_str = ""
                filtered_list = list(filter(lambda s: filter_str in s, self.full_file_list))
                self.window["-FILE_LIST-"].update(filtered_list)

            elif self.event == "-FILE_LIST-" and len(self.values["-FILE_LIST-"]) > 0:
                self.window["-VIDEO_PATH-"].update(self.values["-FILE_LIST-"][0])
                if self.annotation_file is not None:
                    self.load_annotation_entry(self.values["-FILE_LIST-"][0])

            elif self.event == "-LOAD_VIDEO_BTN-":
                threading.Thread(target=self.load_video_into_buffer, daemon=True).start()

            elif self.event == "-VIDEO_SLIDER-":
                if self.video_cap is None or self.video_buffer is None or len(self.video_buffer) == 0:
                    continue
                frame_idx = int(self.values["-VIDEO_SLIDER-"])
                self.window["-FRAME_DISPLAY-"].update(data=ImageTk.PhotoImage(image=Image.fromarray(self.video_buffer[frame_idx])))
                self.window["-SLIDER_VALUE-"].update(f"{self.video_buffer_idx[frame_idx]}")

            elif self.event == "-ANNOTATION_FILE_LOC-":
                try:
                    self.print_anno_log(
                        f"[INFO]: Trying to open annotation file at {self.values['-ANNOTATION_FILE_LOC-']}"
                    )
                    self.annotation_file = pd.read_csv(self.values["-ANNOTATION_FILE_LOC-"])
                except:
                    # create an annotation file
                    fpath = os.path.abspath("./annotations.csv")
                    self.print_anno_log(
                        f"[ERROR]: Error opening annotation file. "
                        + f"Creating new annotation file with header at {fpath}"
                    )
                    self.window["-ANNOTATION_FILE_LOC-"].update(fpath)
                    if not os.path.exists(fpath):
                        with open(fpath, "w") as f:
                            # write the headers
                            f.write(f"{','.join(list(self.annokey_to_elmkey.keys()))}\n")
                    else:
                        self.print_anno_log(
                            f"[ERROR]: Can't overwrite new annotation file at {fpath} because it exists there"
                        )
                    self.annotation_file = pd.read_csv(fpath)
                if self.values["-VIDEO_PATH-"] != "":
                    self.load_annotation_entry()

            elif self.event == "-ANNO_SUBMIT_BTN-" and self.video_annotations is not None:
                is_annotation_good = True
                for k in self.video_annotations:
                    v = self.values[self.annokey_to_elmkey[k]]
                    self.video_annotations[k] = v
                    if v is None or v == "":
                        self.print_anno_log(f'[ERROR]: Key {k} cannot have None or "" value.')
                        is_annotation_good = False
                        break
                if is_annotation_good:
                    self.annotation_file = pd.concat(
                        [
                            self.annotation_file,
                            pd.DataFrame(
                                [self.video_annotations.values()], columns=list(self.video_annotations.keys())
                            ),
                        ]
                    ).drop_duplicates("file_name", keep="last")
                    self.annotation_file.to_csv(self.values["-ANNOTATION_FILE_LOC-"], index=False)
                    self.print_anno_log(f"[SUCCESS]: Entry submitted.")

        self.window.close()

    def load_annotation_entry(self, path=None):
        path = path if path is not None else self.values["-VIDEO_PATH-"]
        video_file_name = os.path.split(path)[1]
        self.print_anno_log(f"[INFO]: Searching for the annotations for video {video_file_name}")
        anno = self.annotation_file.loc[self.annotation_file["file_name"] == video_file_name]

        if anno is None or len(anno) == 0:
            self.print_anno_log(
                f"[WARN]: Annotation for {video_file_name} does not exists. Submit a new entry."
            )
            self.video_annotations = {k: "" for k in self.annokey_to_elmkey}
            for k in self.video_annotations:
                self.window[self.annokey_to_elmkey[k]].update(self.video_annotations[k])

            celeb_name, yt_id, frame_lobound, frame_upbound, _ = re.findall(
                r"(^\D*)_(.*)_(\d*)_(\d*)(.mp4$)", video_file_name
            )[0]
            self.window[self.annokey_to_elmkey["file_name"]].update(video_file_name)
            self.window[self.annokey_to_elmkey["celeb_name"]].update(celeb_name)
            self.window[self.annokey_to_elmkey["youtube_id"]].update(yt_id)
            self.window[self.annokey_to_elmkey["frame_range"]].update(f"{frame_lobound}-{frame_upbound}")
            self.window[self.annokey_to_elmkey["res_w"]].update(
                f"{self.video_res[0] if self.video_res is not None else ''}"
            )
            self.window[self.annokey_to_elmkey["res_h"]].update(
                f"{self.video_res[1] if self.video_res is not None else ''}"
            )
            self.window[self.annokey_to_elmkey["chop_begin"]].update("-1")
            self.window[self.annokey_to_elmkey["chop_end"]].update("-1")

        else:
            anno = list(anno.to_numpy()[0])
            self.print_anno_log(f"[INFO]: Annotation for {video_file_name} exists. Entry Loaded.")
            self.video_annotations = {k: v for k, v in zip(list(self.annokey_to_elmkey.keys()), anno)}
            for k in self.video_annotations:
                self.window[self.annokey_to_elmkey[k]].update(self.video_annotations[k])

    def load_video_into_buffer(self):
        self.window["-VIDEO_SLIDER-"].update(disabled=True)
        self.video_cap = cv2.VideoCapture(self.values["-VIDEO_PATH-"])

        self.video_res = (
            self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
        )
        self.window[self.annokey_to_elmkey["res_w"]].update(f"{self.video_res[0]}")
        self.window[self.annokey_to_elmkey["res_h"]].update(f"{self.video_res[1]}")
        self.video_cap.release()

        vr = decord.VideoReader(self.values["-VIDEO_PATH-"], width=FRAME_DISPLAY_SIZE[0], height=FRAME_DISPLAY_SIZE[1])
        self.video_buffer_idx = list(range(0, len(vr), SAMPLE_EVERY_N_FRAME))
        self.video_buffer = vr.get_batch(self.video_buffer_idx).asnumpy()

        self.window["-VIDEO_LOAD_PROGRESS-"].update(100.0)
        self.window["-VIDEO_SLIDER-"].update(disabled=False, range=(0, len(self.video_buffer) - 1), value=0)
        self.window["-SLIDER_VALUE-"].update("0")
        self.window["-FRAME_DISPLAY-"].update(data=ImageTk.PhotoImage(image=Image.fromarray(self.video_buffer[0])))

    def print_anno_log(self, message):
        if "[INFO]" in message:
            self.window["-ANNOTATION_LOG-"].print(message, colors=("blue", "white"))
        elif "[SUCCESS]" in message:
            self.window["-ANNOTATION_LOG-"].print(message, colors=("green", "white"))
        elif "[WARN]" in message or "[WARNING]" in message:
            self.window["-ANNOTATION_LOG-"].print(message, colors=("#f08832", "white"))
        elif "[ERROR]" in message:
            self.window["-ANNOTATION_LOG-"].print(message, colors=("red", "yellow"))
        else:
            self.window["-ANNOTATION_LOG-"].print(message, colors=("black", "white"))

    @property
    def file_browser(self):
        return [
            [
                sg.Text("Folder", size=(5, 1)),
                sg.In(size=(50, 10), enable_events=True, key="-FOLDER_LOCATION-", expand_x=True),
                sg.FolderBrowse(initial_folder="."),
            ],
            [
                sg.Text("Filter", size=(5, 1)),
                sg.In(size=(50, 10), enable_events=True, key="-FILTER_FILE_LIST-", expand_x=True),
                sg.Button("Go!", key="-FILTER_FILE_LIST_BTN-"),
            ],
            [
                sg.Listbox(
                    values=[],
                    enable_events=True,
                    size=(50, 20),
                    auto_size_text=True,
                    key="-FILE_LIST-",
                    expand_x=True,
                )
            ],
        ]

    @property
    def video_examiner(self):
        return [
            [
                sg.In(default_text="", size=(40, 1), key="-VIDEO_PATH-", readonly=True, expand_x=True),
                sg.Button("Load!", key="-LOAD_VIDEO_BTN-"),
            ],
            [
                sg.ProgressBar(
                    size=(40, 7),
                    max_value=100,
                    orientation="h",
                    bar_color=("green", "white"),
                    key="-VIDEO_LOAD_PROGRESS-",
                    expand_x=True,
                )
            ],
            [sg.Image("", size=FRAME_DISPLAY_SIZE, key="-FRAME_DISPLAY-", background_color="green")],
            [
                sg.Slider(
                    range=(0, 1),
                    default_value=0,
                    size=(40, 15),
                    orientation="horizontal",
                    disable_number_display=True,
                    enable_events=True,
                    key="-VIDEO_SLIDER-",
                    expand_x=True,
                )
            ],
            [sg.Text("Load media to start", key="-SLIDER_VALUE-")],
        ]

    @property
    def annotating_ui(self):
        return [
            [
                sg.Text("File", size=(5, 1)),
                sg.In(size=(50, 10), enable_events=True, key="-ANNOTATION_FILE_LOC-", expand_x=True),
                sg.FileBrowse(initial_folder="."),
            ],
            [
                sg.Frame(
                    "Annotation fields",
                    [
                        [
                            sg.Frame(
                                "file_name",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_FILE_NAME-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "celeb_name",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_CELEB_NAME-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "youtube_id",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_YT_ID-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "frame_range",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_FRAME_RANGE-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "res_w",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_RES_W-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "res_h",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_RES_H-"),
                                    ]
                                ],
                            ),
                        ],
                        [
                            sg.Frame(
                                "is_watermarked",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_WATERMARK-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "is_pristine",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_PRISTINE-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "chop_begin",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_CHOP_BEGIN-"),
                                    ]
                                ],
                            ),
                            sg.Frame(
                                "chop_end",
                                [
                                    [
                                        sg.In(size=(15, 10), key="-ANNO_CHOP_END-"),
                                    ]
                                ],
                            ),
                        ],
                    ],
                    size=(800, 120),
                    expand_x=True,
                ),
                sg.Button("Submit", key="-ANNO_SUBMIT_BTN-"),
            ],
            [
                sg.Multiline(
                    size=(15, 5),
                    auto_size_text=True,
                    font="arial 11 bold",
                    rstrip=True,
                    key="-ANNOTATION_LOG-",
                    disabled=True,
                    write_only=True,
                    expand_x=True,
                    expand_y=True,
                )
            ],
        ]


if __name__ == "__main__":
    gui = ClipAnnotationGUI()
    gui.run()
