using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Generates a curved (cylindrical) screen mesh and applies a texture.
/// Supports stereo side-by-side textures by generating two child meshes
/// that map the left/right halves of the texture.
/// Attach to an empty GameObject (preferably parented to the camera/head).
/// </summary>
[ExecuteInEditMode]
public class CurvedScreen : MonoBehaviour
{
    [Header("Geometry")]
    public float radius = 1.5f;
    [Range(10, 170)]
    public float horizontalFovDeg = 90f;
    public float height = 0.8f;
    public int widthSegments = 48;
    public int heightSegments = 4;

    [Header("Stereo")]
    public bool stereoSideBySide = false;
    public float ipd = 0.064f; // used when stereo: offset the left/right meshes slightly

    [Header("Material")]
    public Material materialTemplate;

    private GameObject leftObj;
    private GameObject rightObj;
    private GameObject monoObj;

    void OnValidate()
    {
        // regenerate when parameters change in editor
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

        // When entering Play Mode, the editor can leave already-generated children
        // under this object. Clear any matching runtime/editor leftovers before
        // creating a fresh curved screen.
        CleanupGeneratedChildren();

        if (stereoSideBySide)
        {
            leftObj = CreateScreenPart("LeftScreen", 0.0f, 0.5f);
            rightObj = CreateScreenPart("RightScreen", 0.5f, 0.5f);

            // offset halves slightly toward each eye
            leftObj.transform.localPosition = new Vector3(-ipd * 0.5f, 0f, 0f);
            rightObj.transform.localPosition = new Vector3(ipd * 0.5f, 0f, 0f);
        }
        else
        {
            monoObj = CreateScreenPart("MonoScreen", 0f, 1f);
        }
    }

    private void CleanupChildren()
    {
        DestroyObject(leftObj);
        DestroyObject(rightObj);
        DestroyObject(monoObj);

        leftObj = null;
        rightObj = null;
        monoObj = null;
    }

    private void CleanupGeneratedChildren()
    {
        for (int i = transform.childCount - 1; i >= 0; i--)
        {
            Transform child = transform.GetChild(i);
            if (child == null)
                continue;

            if (child.name == "LeftScreen" || child.name == "RightScreen" || child.name == "MonoScreen")
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

    private GameObject CreateScreenPart(string name, float uOffset, float uScale)
    {
        var go = new GameObject(name);
        go.transform.SetParent(transform, false);

        var mf = go.AddComponent<MeshFilter>();
        var mr = go.AddComponent<MeshRenderer>();

        Mesh mesh = GenerateCurvedMesh(radius, horizontalFovDeg, height, widthSegments, heightSegments, uOffset, uScale);
        mf.sharedMesh = mesh;

        Material mat = null;
        if (materialTemplate != null)
            mat = new Material(materialTemplate);
        else
            mat = new Material(Shader.Find("Unlit/Texture"));

        // set default tiling/offset if needed
        mat.mainTextureScale = new Vector2(1f, 1f);
        mat.mainTextureOffset = new Vector2(0f, 0f);

        mr.sharedMaterial = mat;
        return go;
    }

    private Mesh GenerateCurvedMesh(float radius, float fovDeg, float height, int wSeg, int hSeg, float uOffset, float uScale)
    {
        Mesh mesh = new Mesh();
        mesh.name = "CurvedScreenMesh";

        int vertsW = wSeg + 1;
        int vertsH = hSeg + 1;
        Vector3[] verts = new Vector3[vertsW * vertsH];
        Vector3[] normals = new Vector3[verts.Length];
        Vector2[] uvs = new Vector2[verts.Length];

        float halfH = height * 0.5f;
        float halfAngle = Mathf.Deg2Rad * (fovDeg * 0.5f);

        for (int y = 0; y < vertsH; y++)
        {
            float v = (float)y / (hSeg);
            float yy = Mathf.Lerp(-halfH, halfH, v);
            for (int x = 0; x < vertsW; x++)
            {
                float u = (float)x / (wSeg);
                float theta = Mathf.Lerp(-halfAngle, halfAngle, u);
                float px = Mathf.Sin(theta) * radius;
                float pz = Mathf.Cos(theta) * radius;
                int idx = y * vertsW + x;
                verts[idx] = new Vector3(px, yy, pz);
                normals[idx] = (-new Vector3(px, yy, pz)).normalized; // face inward toward origin/camera
                float uvx = u * uScale + uOffset;
                uvs[idx] = new Vector2(uvx, v);
            }
        }

        List<int> tris = new List<int>();
        for (int y = 0; y < hSeg; y++)
        {
            for (int x = 0; x < wSeg; x++)
            {
                int i0 = y * vertsW + x;
                int i1 = i0 + 1;
                int i2 = i0 + vertsW;
                int i3 = i2 + 1;

                tris.Add(i0);
                tris.Add(i2);
                tris.Add(i1);

                tris.Add(i1);
                tris.Add(i2);
                tris.Add(i3);
            }
        }

        mesh.vertices = verts;
        mesh.normals = normals;
        mesh.uv = uvs;
        mesh.triangles = tris.ToArray();
        mesh.RecalculateBounds();
        return mesh;
    }

    /// <summary>
    /// Assign the incoming video texture to the generated screen(s).
    /// </summary>
    public void SetTexture(Texture tex)
    {
        if (stereoSideBySide)
        {
            if (leftObj)
            {
                var mr = leftObj.GetComponent<MeshRenderer>();
                if (mr != null)
                {
                    mr.sharedMaterial.mainTexture = tex;
                    mr.sharedMaterial.SetTextureScale("_MainTex", new Vector2(0.5f, 1f));
                    mr.sharedMaterial.SetTextureOffset("_MainTex", new Vector2(0f, 0f));
                }
            }
            if (rightObj)
            {
                var mr = rightObj.GetComponent<MeshRenderer>();
                if (mr != null)
                {
                    mr.sharedMaterial.mainTexture = tex;
                    mr.sharedMaterial.SetTextureScale("_MainTex", new Vector2(0.5f, 1f));
                    mr.sharedMaterial.SetTextureOffset("_MainTex", new Vector2(0.5f, 0f));
                }
            }
        }
        else
        {
            if (monoObj)
            {
                var mr = monoObj.GetComponent<MeshRenderer>();
                if (mr != null)
                {
                    mr.sharedMaterial.mainTexture = tex;
                    mr.sharedMaterial.SetTextureScale("_MainTex", new Vector2(1f, 1f));
                    mr.sharedMaterial.SetTextureOffset("_MainTex", new Vector2(0f, 0f));
                }
            }
        }
    }

    void OnDestroy()
    {
        CleanupChildren();
    }
}
