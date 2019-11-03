preview_verts = None
preview_uvs = None
preview_is_quads = False

def set_preview_data(verts, uvs, is_quads=True):
    """
    Set the preview data for SprytileGUI to draw
    :param verts:
    :param uvs:
    :param is_quads:
    :return:
    """
    global preview_verts, preview_uvs, preview_is_quads

    preview_verts = verts
    preview_uvs = uvs
    preview_is_quads = is_quads


def clear_preview_data():
    global preview_verts, preview_uvs, preview_is_quads
    
    preview_verts = None
    preview_uvs = None
    preview_is_quads = True