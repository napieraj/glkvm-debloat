# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


# =====
# The device half of the plugin foundation.
#
# This package is deliberately separate from kvmd.plugins: that is the plugin
# *tree* that get_plugin_class() imports from, while this is the plugin
# *manager* that decides what is allowed to land in it. Putting the manager
# under kvmd/plugins/ would make it look like a plugin type to the loader.
#
# Everything here implements contract/plugins, which is vendored
# byte-identically into kazbek. Neither repo depends on the other; they meet
# only at that contract, and each proves conformance against the same vectors.
