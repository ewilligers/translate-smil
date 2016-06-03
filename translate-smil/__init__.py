from __future__ import print_function
import collections
import os
import re
import stat
import sys
from os import path

from bs4 import BeautifulSoup

MODE_CSS = '--css'
MODE_WA = '--wa'
MODE_FRAME = '--frame'

LENGTH_PROPERTIES = [
    'font-size',
    'letter-spacing',
    'word-spacing']


def quit(status, *args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.exit(status)


def quit_usage():
    quit(os.EX_USAGE, ('usage: python -m translate-smil  --css|--wa|--frame  '
                       '<input-path>  <output-path>'))


def quit_unsupported(feature):
    quit(os.EX_UNAVAILABLE, 'The SMIL feature "' + feature +
         '" is not currently supported by translate-smil.')


def transform_to_css(transform_type, value):
    if transform_type == 'rotate':
        rotation = re.split(',| ', value)
        if len(rotation) == 1:
            return 'rotate(' + rotation[0] + 'deg)'
        if len(rotation) != 3:
            quit_unsupported('bad rotation')
        return ('translate(' + rotation[1] + 'px, ' + rotation[2] + 'px)' +
                ' rotate(' + rotation[0] + 'deg)' +
                ' translate(-' + rotation[1] + 'px, -' + rotation[2] + 'px)')

    if transform_type == 'scale':
        scale = re.split(',| ', value)
        if len(scale) == 1:
            return 'scale(' + scale[0] + ')'
        if len(scale) != 2:
            quit_unsupported('bad scale')
        return 'scale(' + scale[0] + ', ' + scale[1] + ')'

    if transform_type == 'translate':
        translate = re.split(',| ', value)
        if len(translate) == 1:
            return 'translate(' + translate[0] + 'px)'
        if len(translate) != 2:
            quit_unsupported('bad translate')
        return 'translate(' + translate[0] + 'px, ' + translate[1] + 'px)'

    if transform_type == 'skewX':
        return 'skewX(' + value + 'deg)'

    if transform_type == 'skewY':
        return 'skewY(' + value + 'deg)'


def double_to_string(value):
    return '{0:g}'.format(value)


def milliseconds_to_css(value):
    if value.endswith('00'):
        return double_to_string(float(value) / 1000.) + 's'
    else:
        return value + 'ms'


def clock_value_to_milliseconds(dur):
    if dur.endswith('ms'):
        return dur[:-2]
    if dur.endswith('s'):
        return double_to_string(float(dur[:-1]) * 1000)
    if dur.endswith('min'):
        return double_to_string(float(dur[:-3]) * 60000)
    if dur.endswith('h'):
        return double_to_string(float(dur[:-1]) * 3600000)

    parts = map(float, re.split(':', dur))
    if len(parts) == 3:
        return double_to_string(((parts[0] * 60 + parts[1]) * 60 +
                                 parts[0]) * 1000)
    if len(parts) == 2:
        return double_to_string((parts[0] * 60 + parts[1]) * 1000)
    quit_unsupported('dur value \"' + dur + '\"')


def to_camel_case(property):
    return property[0] + property.title().replace("-", "")[1:]


def translate_soup(soup, mode):
    animate_elements = soup.find_all('animate')

    animate_motion_elements = soup.find_all('animateMotion')

    animate_transform_elements = soup.find_all('animateTransform')

    set_elements = soup.find_all('set')

    animation_elements = []
    animation_elements.extend(animate_elements)
    animation_elements.extend(animate_motion_elements)
    animation_elements.extend(animate_transform_elements)
    animation_elements.extend(set_elements)

    if not animation_elements:
        # The document has no SMIL animations
        return

    head = soup.head
    svg = soup.svg
    if mode == MODE_CSS or len(animate_motion_elements) > 0:
        style = soup.style
        if not style:
            style = soup.new_tag('style')
            if head:
                head.append(style)
            elif svg:
                svg.append(style)
            else:
                quitMissing('svg')
        if not style.string:
            style.string = ''

    if mode == MODE_WA:
        script = soup.script
        if not script:
            script = soup.new_tag('script')
            if head:
                head.append(script)
            elif svg:
                svg.append(script)
            else:
                quitMissing('head')
        if not script.string:
            script.string = ''

    counter_dict = collections.defaultdict(int)

    def generateId(prefix):
        counter = counter_dict[prefix]
        while True:
            result = prefix + str(counter)
            counter += 1
            if not soup.find_all(id=result):
                break
        counter_dict[prefix] = counter
        return result

    for animation_element in animation_elements:
        if animation_element.has_attr('id'):
            animation_name = animation_element['id']
        else:
            animation_name = generateId('anim')

        parent = animation_element.parent
        if parent.has_attr('id'):
            targetName = parent['id']
        else:
            targetName = generateId(parent.name)
            parent['id'] = targetName

        if animation_element.name == 'animateTransform':
            if len(parent.find_all('animateTransform')) > 1:
                quit_unsupported('multiple animateTransform on element')

            if not animation_element.has_attr('type'):
                quit_unsupported('animateTransform element without type')
            transform_type = animation_element['type']

        if animation_element.name == 'animateMotion':
            if len(parent.find_all('animateMotion')) > 1:
                quit_unsupported('multiple animateMotion on element')

            if animation_element.has_attr('rotate'):
                if animation_element['rotate'] == 'auto':
                    motion_rotation = 'auto'
                elif animation_element['rotate'] == 'auto-reverse':
                    motion_rotation = 'reverse'
                else:
                    motion_rotation = animation_element['rotate'] + 'deg'
            else:
                motion_rotation = '0deg'

            motion_path = 'none'
            if(animation_element.has_attr('from') and
               animation_element.has_attr('to')):
                motion_path = ('path(\"M' + animation_element['from'] +
                               ' L' + animation_element['to'] + '\")')
            if animation_element.has_attr('values'):
                segments = re.split(';', animation_element['values'].strip())
                if segments[-1] == '':
                    segments = segments[:-1]
                if len(segments) < 2:
                    quit_unsupported('less than 2 values')
                motion_path = 'path(\"M' + ' L'.join(segments) + '\")'
            if animation_element.has_attr('path'):
                motion_path = 'path(\"' + animation_element['path'] + '\")'
            if(animation_element.mpath and
               animation_element.mpath.has_attr('xlink:href')):
                href = animation_element.mpath['xlink:href']
                if href[:1] == '#':
                    path_element = soup.find(id=href[1:])
                    if path_element.has_attr('d'):
                        motion_path = 'path(\"' + path_element['d'] + '\")'

            style.string += ('\n#' + targetName +
                             ' { motion-path: ' + motion_path +
                             '; motion-rotation: ' + motion_rotation + '; }')
            attribute_name = 'motion-offset'
        else:
            if not animation_element.has_attr('attributeName'):
                quit_unsupported('animation element without attributeName')
            attribute_name = animation_element['attributeName']

        if not animation_element.has_attr('dur'):
            quit_unsupported('animation element without dur')
        elif animation_element['dur'] == 'indefinite':
            quit_unsupported('animation element with indefinite dur')

        if animation_element.name == 'set':
            if(animation_element.has_attr('from') or
               animation_element.has_attr('by') or
               animation_element.has_attr('values') or
               animation_element.has_attr('keyTimes') or
               animation_element.has_attr('keySplines') or
               animation_element.has_attr('calcMode') or
               animation_element.has_attr('additive') or
               animation_element.has_attr('accumulate')):
                quit_unsupported('unexpected attribute for set')
            values = [animation_element['to'],
                      animation_element['to']]
        elif animation_element.name == 'animateMotion':
            values = ['0%', '100%']
        elif animation_element.has_attr('values'):
            values = re.split(';', animation_element['values'].strip())
            if values[-1] == '':
                values = values[:-1]
            if len(values) < 2:
                quit_unsupported('less than 2 values')
            values = map(lambda s: s.strip(), values)
        elif(animation_element.has_attr('from') and
             animation_element.has_attr('to')):
            values = [animation_element['from'],
                      animation_element['to']]
        else:
            quit_unsupported('animation element without from/to or values')

        if animation_element.has_attr('keyTimes'):
            key_times = re.split(';', animation_element['keyTimes'].strip())
            if key_times[-1] == '':
                key_times = key_times[:-1]
            if len(key_times) < 2:
                quit_unsupported('less than 2 keyTimes')
            key_times = map(float, key_times)
        else:
            def key_time(index):
                return index * 1. / (len(values) - 1)
            key_times = map(key_time, range(len(values)))

        if len(key_times) != len(values):
            quit_unsupported('values and keyTimes with different lengths')

        if animation_element.has_attr('keySplines'):
            quit_unsupported('keySplines')

        if animation_element.has_attr('begin'):
            begin = animation_element['begin']
            if 'begin' in begin or 'end' in begin or 'on' in begin:
                quit_unsupported('begin')
            begin = clock_value_to_milliseconds(begin)
        else:
            begin = None

        if animation_element.has_attr('end'):
            quit_unsupported('end')

        if animation_element.has_attr('min'):
            quit_unsupported('min')

        if animation_element.has_attr('max'):
            quit_unsupported('max')

        if animation_element.has_attr('restart'):
            quit_unsupported('restart')

        duration_ms = clock_value_to_milliseconds(animation_element['dur'])

        if animation_element.has_attr('repeatDur'):
            if animation_element['repeatDur'] == 'indefinite':
                repeat_count = 'indefinite'
            else:
                numerator = float(clock_value_to_milliseconds(
                    animation_element['repeatDur']))
                denominator = float(duration_ms)
                if denominator == 0.:
                    quit_unsupported('duration 0 with repeatDur')
                repeat_count = double_to_string(numerator / denominator)
        else:
            repeat_count = 'indefinite'

        if animation_element.has_attr('repeatCount'):
            # We choose the minumum of
            # repeatDur / dur and repeatCount.
            if animation_element['repeatCount'] != 'indefinite':
                if repeat_count != 'indefinite':
                    first = float(repeat_count)
                    second = float(animation_element['repeatCount'])
                    smallest = min(first, second)
                    repeat_count = double_to_string(smallest)
                else:
                    repeat_count = animation_element['repeatCount']
        elif not animation_element.has_attr('repeatDur'):
            repeat_count = '1'

        fill_mode = 'none'
        if animation_element.has_attr('fill'):
            if animation_element['fill'] == 'freeze':
                fill_mode = 'forwards'
            elif animation_element['fill'] != 'remove':
                quit_unsupported('fill \"' + animation_element['fill'] + '\"')

        if animation_element.has_attr('calcMode'):
            quit_unsupported('calcMode')

        if animation_element.has_attr('by'):
            quit_unsupported('by')

        if animation_element.has_attr('additive'):
            quit_unsupported('additive')

        if animation_element.has_attr('accumulate'):
            quit_unsupported('accumulate')

        if animation_element.name == 'animateTransform':
            def convert(value):
                return transform_to_css(transform_type, value)

            values = map(convert, values)

        if attribute_name == 'd':
            def convert(value):
                return "path('" + value + "')"

            values = map(convert, values)
        elif attribute_name in LENGTH_PROPERTIES:
            def convert(value):
                if value[-1].isalpha():
                    return value
                return value + 'px'

            values = map(convert, values)

        if mode == MODE_CSS:
            attribute_duration = ' ' + milliseconds_to_css(duration_ms)
            animation_timing_function = ' linear'
            if begin is not None:
                animation_delay = ' ' + milliseconds_to_css(begin)
            else:
                animation_delay = ''
            if repeat_count == '1':
                animation_iteration_count = ''
            elif repeat_count == 'indefinite':
                animation_iteration_count = ' infinite'
            else:
                animation_iteration_count = ' ' + repeat_count
            animation_direction = ''
            if fill_mode == 'none':
                animation_fill_mode = ''
            else:
                animation_fill_mode = ' ' + fill_mode

            style.string += ('\n#' + targetName +
                             ' { animation: ' + animation_name +
                             attribute_duration + animation_timing_function +
                             animation_delay + animation_iteration_count +
                             animation_direction + animation_fill_mode + '; }')
            style.string += '\n@keyframes ' + animation_name + ' {'

            for index in range(len(values)):
                percentage = double_to_string(key_times[index] * 100) + '%'
                style.string += (' ' + percentage + ' { ' +
                                 attribute_name + ': ' + values[index] + '; }')

            style.string += ' }'
        else:
            keyframes = '['
            for index in range(len(values)):
                keyframes += ' { '
                if animation_element.has_attr('keyTimes'):
                    keyframes += ('offset: ' +
                                  double_to_string(key_times[index]) + ', ')
                keyframes += (to_camel_case(attribute_name) + ': '
                              '\"' + values[index] + '\" },')
            keyframes = keyframes[:-1] + ' ]'

            if fill_mode == 'none' and repeat_count == '1' and begin is None:
                timing = duration_ms
            else:
                timing = '{ duration: ' + duration_ms
                if begin is not None:
                    timing += ', delay: ' + begin
                if fill_mode != 'none':
                    timing += ', fill: \"' + fill_mode + '\"'
                if repeat_count == 'indefinite':
                    timing += ', iterations: Infinity'
                elif repeat_count != '1':
                    timing += ', iterations: ' + repeat_count
                timing += ' }'

            script.string += ('\nwindow.onload = function() { '
                              'document.getElementById("' + targetName + '").'
                              'animate(' + keyframes + ', ' + timing + '); };')

        animation_element.extract()


def translate_file(mode, input_path, output_path):
    print(output_path)

    if input_path.endswith('.svg') and mode == MODE_WA:
        quit_unsupported('JavaScript in .svg images')

    if mode == MODE_FRAME:
        (input_dir, input_name) = os.path.split(input_path)
        output_content = ('<!DOCTYPE html>'
                          '<style>iframe { width: 25% }</style>\n'
                          '<iframe src="../css/' + input_name + '">'
                          '</iframe>\n'
                          '<iframe src="../smil/' + input_name + '">'
                          '</iframe>\n')
        if not input_name.endswith('.svg'):
            output_content += ('<iframe src="../wa/' + input_name + '">'
                               '</iframe>\n')
        with open(output_path, 'w') as output_file:
            output_file.write(output_content)
        return

    if(input_path.endswith('.svg') or
       input_path.endswith('.xml') or
       input_path.endswith('.xhtml')):
        parser = 'lxml-xml'
    else:
        parser = 'html5lib'

    with open(input_path, 'r') as input_file:
        soup = BeautifulSoup(input_file, parser)
        translate_soup(soup, mode)
        with open(output_path, 'w') as output_file:
            output_file.write(soup.prettify())


def main():
    if len(sys.argv) != 4:
        quit_usage()

    mode = sys.argv[1]
    input_path = sys.argv[2]
    output_path = sys.argv[3]

    if mode != MODE_CSS and mode != MODE_WA and mode != MODE_FRAME:
        quit_usage()

    if(stat.S_ISDIR(os.stat(input_path).st_mode) and
       stat.S_ISDIR(os.stat(output_path).st_mode)):
        for filename in os.listdir(input_path):
            if filename.endswith('.svg') and mode == MODE_WA:
                # Skip Web Animations as JavaScript is not supported in images.
                continue

            if mode == MODE_FRAME:
                output_filename = filename.rsplit('.', 1)[0] + '.html'
            else:
                output_filename = filename

            translate_file(mode,
                           path.join(input_path, filename),
                           path.join(output_path, output_filename))

    else:
        translate_file(mode, input_path, output_path)
