using UnityEngine;

/// <summary>
/// Creates a full 360° skybox by mapping stereo video to the front and filling the back with white.
/// Camera is inside the sphere, so normals are inverted.
/// Supports mono or stereo side-by-side textures.
/// </summary>
[ExecuteInEditMode]
public class SkyboxScreen : MonoBehaviour
{
    [Header("Geometry")]
    public float radius = 10f;
    public int widthSegments = 64;
    public int heightSegments = 32;

    [Header("Video")]
    [Range(0f, 180f)]
    public float videoHorizontalFovDeg = 100f;
    [Range(0f, 90f)]
    public float videoVerticalFovDeg = 60f;

    [Header("Stereo")]
    public bool stereoSideBySide = false;

    [Header("Fill")]
    public Color fillColor = Color.white;

    [Header("Material")]
    public Material materialTemplate;

    private GameObject sphereObj;
    private Mesh sphereMesh;

    void OnValidate()
    {
        if (!Application.isPlaying)
            Build();
    }

    void Awake()
    {
        Build();
    }

    public void Build()
    {
        CleanupChildren();
        CleanupGeneratedChildren();
        sphereObj = CreateSkyboxSphere();
    }

    private void CleanupChildren()
    {
        if (sphereObj != null)
            DestroyObject(sphereObj);
        sphereObj = null;
    }

    private void CleanupGeneratedChildren()
    {
        for (int i = transform.childCount - 1; i >= 0; i--)
        {
            Transform child = transform.GetChild(i);
            if (child == null)
                continue;

            if (child.name == "SkyboxSphere")
                DestroyObject(child.gameObject);
        }
    }

    private void DestroyObject(GameObject obj)
    {
        if (obj == null)
            return;
        if (Application.isPlaying)
            Destroy(obj);
        else
            DestroyImmediate(obj);
    }

    private GameObject CreateSkyboxSphere()
    {
        var go = new GameObject("SkyboxSphere");
        go.transform.SetParent(transform, false);

        var mf = go.AddComponent<MeshFilter>();
        var mr = go.AddComponent<MeshRenderer>();

        sphereMesh = GenerateSkyboxMesh(radius, widthSegments, heightSegments);
        mf.sharedMesh = sphereMesh;

        Material mat = null;
        if (materialTemplate != null)
            mat = new Material(materialTemplate);
        else
            mat = new Material(Shader.Find("Unlit/Texture"));

        mat.mainTextureScale = new Vector2(1f, 1f);
        mat.mainTextureOffset = new Vector2(0f, 0f);

        mr.sharedMaterial = mat;
        return go;
    }

    private Mesh GenerateSkyboxMesh(float r, int wSeg, int hSeg)
    {
        Mesh mesh = new Mesh();
        mesh.name = "SkyboxMesh";

        int vertsW = wSeg + 1;
        int vertsH = hSeg + 1;
        Vector3[] verts = new Vector3[vertsW * vertsH];
        Vector3[] normals = new Vector3[verts.Length];
        Vector2[] uvs = new Vector2[verts.Length];

        // Generate sphere: u is azimuth (0..360), v is elevation (0..180)
        for (int y = 0; y < vertsH; y++)
        {
            float v = (float)y / hSeg;
            float phi = Mathf.Lerp(0f, Mathf.PI, v);

            for (int x = 0; x < vertsW; x++)
            {
                float u = (float)x / wSeg;
                float theta = u * 2f * Mathf.PI;

                float px = Mathf.Sin(phi) * Mathf.Cos(theta);
                float py = Mathf.Cos(phi);
                float pz = Mathf.Sin(phi) * Mathf.Sin(theta);

                int idx = y * vertsW + x;
                verts[idx] = new Vector3(px, py, pz) * r;

                // Invert normals so the sphere is viewed from inside
                normals[idx] = -new Vector3(px, py, pz).normalized;

                // UV mapping: compute which part of the video texture this belongs to
                uvs[idx] = ComputeUV(theta, phi, v);
            }
        }

        // Generate triangles
        int[] tris = new int[wSeg * hSeg * 6];
        int triIdx = 0;
        for (int y = 0; y < hSeg; y++)
        {
            for (int x = 0; x < wSeg; x++)
            {
                int i0 = y * vertsW + x;
                int i1 = i0 + 1;
                int i2 = i0 + vertsW;
                int i3 = i2 + 1;

                // Reverse winding for inverted normals
                tris[triIdx++] = i0;
                tris[triIdx++] = i1;
                tris[triIdx++] = i2;

                tris[triIdx++] = i1;
                tris[triIdx++] = i3;
                tris[triIdx++] = i2;
            }
        }

        mesh.vertices = verts;
        mesh.normals = normals;
        mesh.uv = uvs;
        mesh.triangles = tris;
        mesh.RecalculateBounds();
        return mesh;
    }

    private Vector2 ComputeUV(float theta, float phi, float vNorm)
    {
        // theta: 0 (front right) to 2π (back)
        // phi: 0 (top) to π (bottom)

        // Normalize theta to [0, 1]: 0.5 = front center
        float thetaNorm = theta / (2f * Mathf.PI);

        // Check if this vertex is in the front video region (azimuth-wise)
        float halfFovHorizontal = videoHorizontalFovDeg / 360f;
        bool isInVideoAzimuth = Mathf.Abs(thetaNorm - 0.5f) <= halfFovHorizontal;

        if (!isInVideoAzimuth)
        {
            // Outside horizontal FOV - fill region
            return new Vector2(0f, 0f);
        }

        // Inside horizontal FOV. Now check vertical centering based on aspect ratio.
        // Assume the video texture has some aspect ratio. 
        // We'll use videoHorizontalFovDeg and videoVerticalFovDeg to define the "safe" region.

        float halfFovVertical = videoVerticalFovDeg / 360f;
        float centerV = 0.5f; // Centered vertically in the sphere
        bool isInVideoVertical = Mathf.Abs(vNorm - centerV) <= halfFovVertical;

        if (!isInVideoVertical)
        {
            // Outside vertical extent - fill region (top/bottom)
            return new Vector2(0f, 0f);
        }

        // Inside video region: map to texture without stretching
        float videoTheta = (thetaNorm - 0.5f) * 360f;
        float localU = (videoTheta + videoHorizontalFovDeg * 0.5f) / videoHorizontalFovDeg;
        float localV = (vNorm - (centerV - halfFovVertical)) / (halfFovVertical * 2f);

        if (stereoSideBySide)
        {
            // Determine left vs right eye
            bool isLeftEye = thetaNorm < 0.5f;
            if (isLeftEye)
            {
                // Left half of stereo texture
                return new Vector2(localU * 0.5f, localV);
            }
            else
            {
                // Right half of stereo texture
                return new Vector2(0.5f + localU * 0.5f, localV);
            }
        }
        else
        {
            // Mono: use full texture
            return new Vector2(localU, localV);
        }
    }

    /// <summary>
    /// Assign the incoming video texture to the skybox.
    /// </summary>
    public void SetTexture(Texture tex)
    {
        if (sphereObj == null)
            return;

        var mr = sphereObj.GetComponent<MeshRenderer>();
        if (mr != null && mr.sharedMaterial != null)
        {
            mr.sharedMaterial.mainTexture = tex;

            // Create a solid color to fill the back
            var fillTex = new Texture2D(2, 2, TextureFormat.RGB24, false);
            for (int i = 0; i < fillTex.width * fillTex.height; i++)
                fillTex.SetPixel(i % fillTex.width, i / fillTex.width, fillColor);
            fillTex.Apply();

            // Optionally, blend or tint the material to show fill in unused regions
            mr.sharedMaterial.SetColor("_Color", Color.white);
        }
    }

    void OnDestroy()
    {
        CleanupChildren();
    }
}
