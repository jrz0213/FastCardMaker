# -*- coding:utf-8 -*-
#
# Copyright (C) 2018 sthoo <sth201807@gmail.com>
#
# Support: Report an issue at https://github.com/sth2018/FastWordQuery/issues
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version; http://www.gnu.org/copyleft/gpl.html.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from .lang import _

__all__ = ['VERSION', 'Endpoint', 'Template']

VERSION = 'v3.0.0b'


class Endpoint:
    repository = u'https://github.com/jrz0213/FastCardMaker'
    feedback_issue = u'https://github.com/jrz0213/FastCardMaker/issues'
    feedback_mail = u'jiangrz0213@gmail.com'
    check_version = u'jrz0213/FastCardMaker'
    user_guide = u'https://github.com/jrz0213/FastCardMaker#操作指南--user-guides'
    version = VERSION


class Template:
    @staticmethod
    def about_html():
        from html import escape
        from .translations import text as tr
        links = (
            (tr('使用指南'), Endpoint.user_guide),
            (tr('项目地址'), Endpoint.repository),
            (tr('问题反馈'), Endpoint.feedback_issue),
            ('Gmail: ' + Endpoint.feedback_mail, 'mailto:' + Endpoint.feedback_mail),
        )
        return ('<h3>FastCard Maker</h3><p>' + escape(VERSION) + '</p><p>' +
                escape(tr('使用 AI、本地 MDX 词典和网络词典填充 Anki 笔记，制作词汇、概念及其他学习主题的闪卡。')) +
                '</p><p>' + escape(tr('支持自定义字段提示词、批量后台处理和 AI 辅助生成词典解析脚本。')) + '</p><p>' +
                ' · '.join('<a href="' + escape(url, quote=True) + '">' + escape(label) + '</a>'
                           for label, url in links) + '</p><hr/><p>' +
                escape(tr('基于 FastWordQuery（FastWQ）开发，感谢原作者及贡献者。')) + '<br/>' +
                '<a href="https://github.com/sth2018/FastWordQuery">FastWordQuery</a><br/>' +
                'Copyright © 2018 sthoo; FastCard Maker contributors.<br/>' +
                '<a href="' + escape(Endpoint.repository + '/blob/main/LICENSE', quote=True) +
                '">GPL-3.0-or-later</a></p>')
