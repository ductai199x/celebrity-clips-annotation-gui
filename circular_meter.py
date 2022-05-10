"""
    Demo Graph Custom Progress Meter

    The "Graph Element" is a "Gateway Element"
    Looking to create your own custom elements?  Then the Graph Element is an excellent
    place to start.

    This short demo implements a Circular Progress Meter

    The event loop has a little trick some may like....
        Rather than adding a sleep instead use window.read with a timeout
        This has a dual purpose. You get the delay you're after AND your GUI is refreshed

    Copyright 2022 PySimpleGUI
"""

from typing import * 
import PySimpleGUI as sg

# Settings for you to modify are the size of the element, the circle width & color and the font for the % complete
GRAPH_SIZE = (300 , 300)          # this one setting drives the other settings

class CircularMeter():
    def __init__(
        self,
        graph: sg.Element,
        init_percent: float = 0.0,
        size: Tuple[int, int] = (200, 200),
        circle_line_width: int = 10,
        circle_line_color: str = "yellow",
        text_font: str = "Courier",
        text_height: int = 25,
        text_color: str = "yellow"
    ):
        self.graph = graph
        self.current_percent = init_percent
        self.size = size
        self.circle_line_width = circle_line_width
        self.circle_line_color = circle_line_color
        self.text_font = text_font
        self.text_color = text_color
        self.text_height = text_height
        self.text_location = (self.size[0]// 2, self.size[1] // 2)

        self.update(init_percent)

    def update(self, percent_completed):
        self.graph.erase()
        arc_length = percent_completed/100*360+.9
        if arc_length >= 360:
            arc_length = 359.9
        self.graph.draw_arc(
            (self.circle_line_width, self.size[1] - self.circle_line_width), 
            (self.size[0] - self.circle_line_width, self.circle_line_width),
            arc_length, 0, 'arc', arc_color=self.circle_line_color, line_width=self.circle_line_width)
        self.current_percent = percent_completed
        self.graph.draw_text(
            f'{self.current_percent:.1f}%', 
            self.text_location, 
            font=(self.text_font, -self.text_height), color=self.text_color)
    

def main():

    layout = [  [sg.Graph(GRAPH_SIZE, (0,0), GRAPH_SIZE, key='-GRAPH-')],
                [sg.Button('Go')]]


    window = sg.Window('Circlular Meter', layout, finalize=True)

    circular_meter = CircularMeter(window['-GRAPH-'], size=GRAPH_SIZE)

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            break
        for i in range(500):
            circular_meter.update(i/499*100)
            window.read(timeout=5)      # an easy way to make a loop that acts like it has a "sleep" in it

    window.close()

if __name__ == '__main__':
    main()