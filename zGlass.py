bl_info = {
    "name": "zGlass",
    "author": "Joao Victor Superbi",
    "version": (1, 0),
    "blender": (4, 5, 4), 
    "location": "View3D > Sidebar > zGlass",
    "description": "This addon generates a depth map that accurately accounts for and renders glass materials (transparency/refraction) present in the scene.",
    "warning": "",
    "doc_url": "https://github.com/joaosuperb1/zGlass",
    "category": "Development", 
}


import bpy
import numpy as np
from mathutils import Vector 
import math 


MAX_DEPTH = 5
MAX_DIST = 200.0


def normalize(v):
    v.normalize()
    return v

def refract(I, N, ior):

    cos_i = -I.dot(N) 
    eta_i = 1.0
    eta_t = ior
    
    if cos_i < 0: 
        cos_i = -cos_i
        eta_i, eta_t = eta_t, eta_i
        N = -N
        
    eta = eta_i / eta_t
    k = 1 - eta**2 * (1 - cos_i**2)
    
    if k < 0:
        
        return None
    

    scalar = eta * cos_i - math.sqrt(k)
    return normalize(eta * I + scalar * N)

# calcula a chance de reflexao e retorna valores entre 0.0 e 1.0
def fresnel(I, N, ior):
    
    cos_i = -I.dot(N)
    eta_i = 1.0
    eta_t = ior
    
    if cos_i < 0: 
        cos_i = -cos_i
        eta_i, eta_t = eta_t, eta_i
    

    R0 = ((eta_i - eta_t) / (eta_i + eta_t))**2
    

    R = R0 + (1 - R0) * math.pow((1 - cos_i), 5)
    return R


def trace_ray(depsgraph, O, D, depth):
    if depth <= 0:
        return MAX_DIST

    hit, location, normal, index, obj, matrix = bpy.context.scene.ray_cast(
        depsgraph, O, D, distance=MAX_DIST
    )
    
    if not hit:
        return MAX_DIST
    
    distance_to_hit = (location - O).length
    bias = 1e-4 * normal
    mat = obj.active_material
    
    if not mat:
        return distance_to_hit

    mat_type = mat.get("render_type", "Diffuse")
    mat_type = mat_type.strip(' " ') 

    
    if mat_type == "Diffuse":
        return distance_to_hit

    if mat_type == "Mirror":
        reflect_dir = D.reflect(normal)
        return distance_to_hit + trace_ray(depsgraph, location + bias, reflect_dir, depth - 1)

    if mat_type == "Glass":
        ior = mat.get("ior", 1.5) 
        

        reflect_chance = fresnel(D, normal, ior)
        reflect_dir = D.reflect(normal)
        reflected_dist = trace_ray(depsgraph, location + bias, reflect_dir, depth - 1)


        refract_dir = refract(D, normal, ior)
        refracted_dist = 0.0
        
        if refract_dir is None:
            reflect_chance = 1.0
        else:

            # Se D.dot(normal) < 0, estamos entrando -> bias negativo
            # Se D.dot(normal) > 0, estamos saindo -> bias positivo
            is_entering = D.dot(normal) < 0
            refract_bias = -bias if is_entering else bias

            
            # Traça o raio refratado
            refracted_dist = trace_ray(depsgraph, location + refract_bias, refract_dir, depth - 1)
        

        # Mistura os resultados. A distância final é uma média ponderada das duas distâncias
        final_dist = (reflect_chance * reflected_dist) + ((1 - reflect_chance) * refracted_dist)
        
        return distance_to_hit + final_dist


    return distance_to_hit

# Render 
def render_depth_map():
    print("Iniciando renderização de profundidade...")
    
    scene = bpy.context.scene
    cam = scene.camera
    
    if not cam:
        print("Erro: Nenhuma câmera ativa na cena.")
        return

    render = scene.render
    WIDTH = render.resolution_x
    HEIGHT = render.resolution_y
    
    image_name = "Depth Map Render"
    if image_name in bpy.data.images:
        image = bpy.data.images[image_name]
        image.scale(WIDTH, HEIGHT)
    else:
        image = bpy.data.images.new(image_name, width=WIDTH, height=HEIGHT, alpha=True)
    

    pixels = np.zeros(WIDTH * HEIGHT * 4, dtype=np.float32)
    dist_buffer = np.zeros((HEIGHT, WIDTH), dtype=np.float32)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    

    cam_matrix = cam.matrix_world
    cam_pos = cam_matrix.translation
    
    cam_quat = cam_matrix.to_quaternion()
    forward_vec = cam_quat @ Vector((0, 0, -1))
    up_vec = cam_quat @ Vector((0, 1, 0))
    right_vec = cam_quat @ Vector((1, 0, 0))
    
    aspect_ratio = WIDTH / HEIGHT
    
    fov_horizontal = cam.data.angle
    scale_x = math.tan(fov_horizontal / 2)
    scale_y = scale_x / aspect_ratio
    
    if cam.data.sensor_fit == 'VERTICAL':
        fov_vertical = cam.data.angle
        scale_y = math.tan(fov_vertical / 2)
        scale_x = scale_y * aspect_ratio
        

    print(f"Renderizando {WIDTH}x{HEIGHT}...")


    for y in range(HEIGHT):
        for x in range(WIDTH):
            

            px_ndc = (x + 0.5) / WIDTH
            px_screen = (2 * px_ndc - 1) 
            
            py_ndc = (y + 0.5) / HEIGHT
            py_screen = (1 - 2 * py_ndc)
            
            O = cam_pos
            D = normalize(
                (px_screen * scale_x * right_vec) + 
                (py_screen * scale_y * up_vec) + 
                forward_vec
            )

            
            distance = trace_ray(depsgraph, O, D, MAX_DEPTH)
            dist_buffer[y, x] = distance
            
        if (y+1) % 50 == 0:
            print(f"Progresso: {((y+1)/HEIGHT)*100:.2f}%")

    print("Normalizando e salvando imagem...")
    
    valid_distances = dist_buffer[dist_buffer < MAX_DIST]
    
    if valid_distances.size == 0:
        print("Erro: Nenhum raio atingiu a cena.")
        image.pixels.foreach_set(pixels) 
        print("Feito! Imagem 'Depth Map Render' está preta.")
        return

    max_val = np.max(valid_distances)
    min_val = np.min(valid_distances)

    print(f"!!! DEBUG: min_val = {min_val}, max_val = {max_val} !!!")

    depth_range = max_val - min_val

    if depth_range < 1e-6:
        if max_val > 0:
             normalized_buffer = dist_buffer / max_val
             normalized_buffer[normalized_buffer > 1.0] = 1.0
        else:
             normalized_buffer = np.zeros_like(dist_buffer)
    else:
        dist_buffer[dist_buffer > max_val] = max_val
        normalized_buffer = (dist_buffer - min_val) / depth_range

    normalized_buffer = np.flipud(normalized_buffer) 
    
    for i in range(WIDTH * HEIGHT):
        val = normalized_buffer.flat[i]
        idx = i * 4
        pixels[idx]   = val
        pixels[idx+1] = val
        pixels[idx+2] = val
        pixels[idx+3] = 1.0
        
    image.pixels.foreach_set(pixels)
    
    print(f"Feito! Imagem '{image_name}' criada ou atualizada.")
    print("Você pode vê-la no 'Image Editor' do Blender.")

# Mai
if __name__ == "__main__":
    render_depth_map()