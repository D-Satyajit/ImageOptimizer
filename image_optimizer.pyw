import customtkinter as ctk
from PIL import Image, ImageOps, ImageFilter
from PIL.ExifTags import TAGS
import os
import hashlib
import json
import tkinter as tk
from tkinter import filedialog, ttk
import threading
import math
import logging
from datetime import datetime
import re

# Configure error logging
logging.basicConfig(
    filename='image_optimizer.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Set appearance with dark mode styling
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ImageOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Image Optimizer Pro")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        
        # Configure grid layout - 1 column for sidebar, 1 for main content
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Create sidebar with dark mode styling
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color="#2b2b2b")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        # Configure sidebar rows - all content aligned to top
        for i in range(25):
            self.sidebar.grid_rowconfigure(i, weight=0)
        self.sidebar.grid_rowconfigure(24, weight=1)  # Push buttons to bottom
        
        # Create main content area
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#333333")
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=3)  # Preview area
        self.main_frame.grid_rowconfigure(1, weight=7)  # File list area
        self.main_frame.grid_rowconfigure(2, weight=0)  # Status bar area
        
        # Initialize variables
        self.images = []
        self.image_metadata = []
        self.current_image_index = 0
        self.optimized_images = []
        self.output_dir = ""
        self.processing_thread = None
        self.processing = False
        
        # Set up UI components
        self.setup_sidebar()
        self.setup_main_area()
        self.setup_status_bar()
        
        # Initialize in optimization mode
        self.toggle_mode("optimize")
        
    def setup_sidebar(self):
        """Configure sidebar controls with yellow styling for interactive elements"""
        yellow_style = {"fg_color": "#FFCC00", "hover_color": "#FFDD55"}
        
        # ========== MODE SELECTION ==========
        # Mode selection: File Renaming or Image Optimizing
        mode_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        mode_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        self.mode_var = ctk.StringVar(value="optimize")  # Default to image optimizing
        optimize_rb = ctk.CTkRadioButton(
            mode_frame, 
            text="Image Optimize", 
            variable=self.mode_var, 
            value="optimize",
            command=lambda: self.toggle_mode("optimize")
        )
        optimize_rb.pack(side="left", padx=(0, 10))
        
        rename_rb = ctk.CTkRadioButton(
            mode_frame, 
            text="File Rename", 
            variable=self.mode_var, 
            value="rename",
            command=lambda: self.toggle_mode("rename")
        )
        rename_rb.pack(side="left")
        
        # ========== IMAGE OPTIMIZATION CONTROLS ==========
        self.optimize_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.optimize_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        
        # Format settings
        format_label = ctk.CTkLabel(self.optimize_frame, text="Output Format:", anchor="w")
        format_label.grid(row=0, column=0, padx=20, pady=(20, 0), sticky="w")
        
        self.format_var = ctk.StringVar(value="webp")
        formats = ["JPEG", "PNG", "WebP", "AVIF"]
        for i, fmt in enumerate(formats):
            rb = ctk.CTkRadioButton(
                self.optimize_frame, 
                text=fmt, 
                variable=self.format_var, 
                value=fmt.lower(),
                font=("Arial", 10),
                **yellow_style  # Apply yellow styling
            )
            rb.grid(row=i+1, column=0, padx=20, pady=(0, 2), sticky="w")
        
        # Compression settings - default to lossless
        comp_label = ctk.CTkLabel(self.optimize_frame, text="Compression:", anchor="w")
        comp_label.grid(row=5, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.comp_mode = ctk.StringVar(value="lossless")  # Set default to lossless
        lossless_rb = ctk.CTkRadioButton(
            self.optimize_frame, 
            text="Lossless", 
            variable=self.comp_mode, 
            value="lossless",
            font=("Arial", 10),
            **yellow_style
        )
        lossless_rb.grid(row=6, column=0, padx=20, pady=(0, 2), sticky="w")
        
        lossy_rb = ctk.CTkRadioButton(
            self.optimize_frame, 
            text="Lossy", 
            variable=self.comp_mode, 
            value="lossy",
            font=("Arial", 10),
            **yellow_style
        )
        lossy_rb.grid(row=7, column=0, padx=20, pady=(0, 10), sticky="w")
        
        # Quality slider
        self.quality_label = ctk.CTkLabel(self.optimize_frame, text="Quality: 100%")
        self.quality_label.grid(row=8, column=0, padx=20, pady=(0, 0), sticky="w")
        
        self.quality_slider = ctk.CTkSlider(
            self.optimize_frame, 
            from_=10, 
            to=100, 
            number_of_steps=90,
            command=self.update_quality_label
        )
        self.quality_slider.set(100)
        self.quality_slider.grid(row=9, column=0, padx=20, pady=(5, 10), sticky="ew")
        
        # Responsive sizes
        size_label = ctk.CTkLabel(self.optimize_frame, text="Responsive Sizes:", anchor="w")
        size_label.grid(row=10, column=0, padx=20, pady=(5, 0), sticky="w")
        
        # Size presets - Added 2K and 4K resolutions
        self.size_presets = ctk.CTkComboBox(
            self.optimize_frame,
            values=[
                "Mobile (480px)", 
                "Tablet (768px)", 
                "Desktop (1080px)", 
                "Full HD (1920px)",
                "2K (2560px)",      # New 2K resolution
                "4K (3840px)",      # New 4K resolution
                "Custom..."
            ],
            command=self.on_size_preset_select
        )
        self.size_presets.set("Full HD (1920px)")
        self.size_presets.grid(row=11, column=0, padx=20, pady=(5, 0), sticky="ew")
        
        # Custom size entry
        custom_size_frame = ctk.CTkFrame(self.optimize_frame, fg_color="transparent")
        custom_size_frame.grid(row=12, column=0, padx=20, pady=(5, 0), sticky="ew")
        custom_size_frame.grid_columnconfigure(0, weight=1)
        custom_size_frame.grid_columnconfigure(1, weight=0)
        custom_size_frame.grid_columnconfigure(2, weight=1)
        
        # Width entry (disabled by default)
        self.width_var = ctk.StringVar(value="1920")
        self.width_entry = ctk.CTkEntry(custom_size_frame, placeholder_text="Width", 
                                  textvariable=self.width_var, width=80, state="disabled")
        self.width_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        ctk.CTkLabel(custom_size_frame, text="x").grid(row=0, column=1, padx=5)
        
        # Height entry (disabled, auto-calculated)
        self.height_var = ctk.StringVar(value="")
        self.height_entry = ctk.CTkEntry(custom_size_frame, placeholder_text="Height", 
                                   textvariable=self.height_var, width=80, state="disabled")
        self.height_entry.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        
        # Additional options
        self.progressive_var = ctk.BooleanVar(value=True)
        progressive_cb = ctk.CTkCheckBox(
            self.optimize_frame, 
            text="Progressive JPEG", 
            variable=self.progressive_var,
            font=("Arial", 10),
            **yellow_style
        )
        progressive_cb.grid(row=13, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.lqip_var = ctk.BooleanVar(value=False)
        lqip_cb = ctk.CTkCheckBox(
            self.optimize_frame, 
            text="Generate LQIP", 
            variable=self.lqip_var,
            font=("Arial", 10),
            **yellow_style
        )
        lqip_cb.grid(row=14, column=0, padx=20, pady=(0, 2), sticky="w")
        
        self.strip_meta_var = ctk.BooleanVar(value=False)
        strip_cb = ctk.CTkCheckBox(
            self.optimize_frame, 
            text="Strip Metadata", 
            variable=self.strip_meta_var,
            font=("Arial", 10),
            **yellow_style
        )
        strip_cb.grid(row=15, column=0, padx=20, pady=(0, 2), sticky="w")
        
        # Changed default to unchecked for hashed filenames
        self.hash_names_var = ctk.BooleanVar(value=False)  # Default to unchecked
        hash_cb = ctk.CTkCheckBox(
            self.optimize_frame, 
            text="Hashed Filenames", 
            variable=self.hash_names_var,
            font=("Arial", 10),
            **yellow_style
        )
        hash_cb.grid(row=16, column=0, padx=20, pady=(0, 10), sticky="w")
        
        # ========== FILE RENAMING CONTROLS ==========
        self.rename_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.rename_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        
        # Renaming section title
        rename_label = ctk.CTkLabel(self.rename_frame, text="Bulk Rename:", font=("Arial", 12, "bold"))
        rename_label.grid(row=0, column=0, padx=20, pady=(5, 0), sticky="w")
        
        # Renaming format selection
        self.rename_format_var = ctk.StringVar(value="sequential")
        rename_formats = [
            "Sequential Numbering",
            "Alphanumeric Pattern",
            "Add Prefix/Suffix",
            "Date and Time",
            "Custom Pattern"
        ]
        
        format_dropdown = ctk.CTkComboBox(
            self.rename_frame,
            values=rename_formats,
            variable=self.rename_format_var,
            command=self.update_rename_preview
        )
        format_dropdown.grid(row=1, column=0, padx=20, pady=(5, 0), sticky="ew")
        
        # Prefix input
        prefix_frame = ctk.CTkFrame(self.rename_frame, fg_color="transparent")
        prefix_frame.grid(row=2, column=0, padx=20, pady=(5, 0), sticky="ew")
        ctk.CTkLabel(prefix_frame, text="Prefix:").pack(side="left", padx=(0, 5))
        self.prefix_var = ctk.StringVar(value="")
        self.prefix_var.trace_add("write", self.update_rename_preview)
        prefix_entry = ctk.CTkEntry(prefix_frame, textvariable=self.prefix_var, width=100)
        prefix_entry.pack(side="left", fill="x", expand=True)
        
        # Suffix input
        suffix_frame = ctk.CTkFrame(self.rename_frame, fg_color="transparent")
        suffix_frame.grid(row=3, column=0, padx=20, pady=(5, 0), sticky="ew")
        ctk.CTkLabel(suffix_frame, text="Suffix:").pack(side="left", padx=(0, 5))
        self.suffix_var = ctk.StringVar(value="")
        self.suffix_var.trace_add("write", self.update_rename_preview)
        suffix_entry = ctk.CTkEntry(suffix_frame, textvariable=self.suffix_var, width=100)
        suffix_entry.pack(side="left", fill="x", expand=True)
        
        # Date/time options
        date_time_frame = ctk.CTkFrame(self.rename_frame, fg_color="transparent")
        date_time_frame.grid(row=4, column=0, padx=20, pady=(5, 0), sticky="ew")
        
        self.include_date_var = ctk.BooleanVar(value=True)
        date_cb = ctk.CTkCheckBox(
            date_time_frame, 
            text="Date", 
            variable=self.include_date_var,
            command=self.update_rename_preview
        )
        date_cb.pack(side="left", padx=(0, 10))
        
        self.include_time_var = ctk.BooleanVar(value=True)
        time_cb = ctk.CTkCheckBox(
            date_time_frame, 
            text="Time", 
            variable=self.include_time_var,
            command=self.update_rename_preview
        )
        time_cb.pack(side="left")
        
        # Rename preview button
        preview_btn = ctk.CTkButton(
            self.rename_frame,
            text="Preview Rename",
            command=self.update_rename_preview,
            fg_color="#5bc0de"
        )
        preview_btn.grid(row=5, column=0, padx=20, pady=(10, 5), sticky="ew")
        
        # ========== COMMON CONTROLS ==========
        # Browse Files button (blue color)
        self.browse_btn = ctk.CTkButton(
            self.sidebar, 
            text="Browse Files", 
            command=self.browse_files,
            fg_color="#1E90FF",  # Dodger blue color
            hover_color="#4169E1",  # Royal blue hover
            font=("Arial", 12, "bold")
        )
        self.browse_btn.grid(row=17, column=0, padx=20, pady=(10, 10), sticky="ew")
        
        # Process button
        self.process_btn = ctk.CTkButton(
            self.sidebar, 
            text="Optimize Images", 
            command=self.start_processing
        )
        self.process_btn.grid(row=18, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        # Apply rename button
        self.rename_btn = ctk.CTkButton(
            self.sidebar,
            text="Apply Rename",
            command=self.apply_rename,
            fg_color="#5cb85c"
        )
        self.rename_btn.grid(row=18, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        # Clear and reset button
        reset_btn = ctk.CTkButton(
            self.sidebar, 
            text="Clear All & Reset", 
            command=self.reset_application,
            fg_color="#c9302c", 
            hover_color="#d9534f" 
        )
        reset_btn.grid(row=19, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        # Initially hide the rename button
        self.rename_btn.grid_remove()
        
    def toggle_mode(self, mode):
        """Enable/disable controls based on selected mode"""
        if mode == "optimize":
            # Show optimization controls and hide renaming controls
            self.optimize_frame.grid()
            self.rename_frame.grid_remove()
            
            # Update buttons
            self.process_btn.grid()
            self.rename_btn.grid_remove()
            self.browse_btn.configure(text="Browse Images")
            
            # Disable renaming-specific features
            self.file_frame.grid()  # Show file list
            self.preview_frame.grid()  # Show preview
            
        else:  # "rename"
            # Show renaming controls and hide optimization controls
            self.rename_frame.grid()
            self.optimize_frame.grid_remove()
            
            # Update buttons
            self.process_btn.grid_remove()
            self.rename_btn.grid()
            self.browse_btn.configure(text="Browse Files")
            
            # Hide preview for non-image files
            self.preview_frame.grid_remove()
            
        # Clear existing selection when switching modes
        self.images = []
        self.image_metadata = []
        self.update_file_list()
        self.update_status_bar("Ready")
        
    def browse_files(self):
        """Open file dialog to browse for files"""
        # Determine file types based on current mode
        if self.mode_var.get() == "optimize":
            # In optimization mode, only show image files including WEBP
            filetypes = (
                ("Image files", "*.jpg *.jpeg *.png *.bmp *.tiff *.gif *.webp"),
                ("All files", "*.*")
            )
        else:
            # In renaming mode, show all file types
            filetypes = (("All files", "*.*"),)
        
        # Open file dialog with appropriate file filters
        files = filedialog.askopenfilenames(
            title="Select Files" if self.mode_var.get() == "rename" else "Select Images",
            filetypes=filetypes
        )
        
        if files:
            # Store files regardless of type in renaming mode
            if self.mode_var.get() == "rename":
                self.images = list(files)
            else:
                # Filter valid image files in optimization mode
                valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp')
                self.images = [f for f in files if os.path.splitext(f)[1].lower() in valid_extensions]
            
            if not self.images:
                self.update_status_bar("No valid files found")
                return
                
            # Extract metadata - handles both image and non-image files
            self.image_metadata = [self.extract_metadata(f) for f in self.images]
            self.update_file_list()
            self.current_image_index = 0
            
            # Only show image preview in optimization mode
            if self.mode_var.get() == "optimize":
                self.show_image()
                self.show_work_area()
                
            self.update_status_bar()
            self.update_rename_preview()
        
    # ========== FILE RENAMING MODULE ==========
    def generate_new_filename(self, path, index):
        """
        Generate new filename based on selected renaming pattern
        - path: Original file path
        - index: Position in file list (for sequential numbering)
        Returns new filename with extension
        """
        # Get file extension
        base_name = os.path.basename(path)
        name, ext = os.path.splitext(base_name)
        ext = ext.lower()  # Standardize extension case
        
        # Get renaming pattern
        pattern = self.rename_format_var.get()
        
        # Apply selected pattern
        if pattern == "Sequential Numbering":
            return f"image_{index+1}{ext}"
        
        elif pattern == "Alphanumeric Pattern":
            # Generate pattern: img_A1, img_B2, etc.
            letter = chr(65 + (index // 10))  # A, B, C...
            number = index % 10 + 1
            return f"img_{letter}{number}{ext}"
        
        elif pattern == "Add Prefix/Suffix":
            prefix = self.prefix_var.get()
            suffix = self.suffix_var.get()
            return f"{prefix}{name}{suffix}{ext}"
        
        elif pattern == "Date and Time":
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d") if self.include_date_var.get() else ""
            time_str = now.strftime("%H-%M") if self.include_time_var.get() else ""
            
            # Combine date and time
            dt_str = ""
            if date_str and time_str:
                dt_str = f"{date_str}_{time_str}"
            elif date_str:
                dt_str = date_str
            elif time_str:
                dt_str = time_str
                
            return f"FILE_{dt_str}_{index+1}{ext}"
        
        elif pattern == "Custom Pattern":
            # Allow user-defined pattern with placeholders
            custom_pattern = f"{self.prefix_var.get()}_{{index}}_{self.suffix_var.get()}"
            
            # Get date/time if needed
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d") if self.include_date_var.get() else ""
            time_str = now.strftime("%H-%M") if self.include_time_var.get() else ""
            
            # Replace placeholders
            custom_pattern = custom_pattern.replace("{prefix}", self.prefix_var.get())
            custom_pattern = custom_pattern.replace("{suffix}", self.suffix_var.get())
            custom_pattern = custom_pattern.replace("{index}", str(index+1))
            custom_pattern = custom_pattern.replace("{date}", date_str)
            custom_pattern = custom_pattern.replace("{time}", time_str)
            custom_pattern = custom_pattern.replace("{name}", name)
            
            return f"{custom_pattern}{ext}"
        
        # Fallback to original name
        return base_name
    
    def update_rename_preview(self, *args):
        """Update the file list to show preview of new filenames"""
        if not self.images:
            return
            
        # Update treeview with new names
        for i, item in enumerate(self.tree.get_children()):
            # Get original metadata
            values = list(self.tree.item(item, "values"))
            
            if len(values) > 0:
                # Generate new filename
                new_name = self.generate_new_filename(self.images[i], i)
                
                # Update the filename in metadata display
                values[0] = new_name
                self.tree.item(item, values=values)
    
    def apply_rename(self):
        """Apply the selected renaming pattern to all loaded files"""
        if not self.images:
            self.update_status_bar("No files to rename")
            return
            
        try:
            renamed_count = 0
            
            # Create a copy of the current images list to avoid modification during iteration
            original_paths = self.images.copy()
            
            for i, path in enumerate(original_paths):
                # Generate new filename
                new_name = self.generate_new_filename(path, i)
                dir_path = os.path.dirname(path)
                new_path = os.path.join(dir_path, new_name)
                
                # Skip if name hasn't changed
                if os.path.basename(path) == new_name:
                    continue
                
                # Handle filename conflicts
                counter = 1
                base_new_path = new_path
                while os.path.exists(new_path):
                    name, ext = os.path.splitext(base_new_path)
                    new_path = f"{name}_{counter}{ext}"
                    counter += 1
                
                # Rename the file
                os.rename(path, new_path)
                renamed_count += 1
                
                # Update the file path in our list
                self.images[i] = new_path
            
            # Update metadata and UI
            self.image_metadata = [self.extract_metadata(f) for f in self.images]
            self.update_file_list()
            self.update_status_bar(f"Renamed {renamed_count} files successfully")
            
        except Exception as e:
            logging.error(f"Error renaming files: {str(e)}")
            self.update_status_bar(f"Error renaming files: {str(e)}")
    
    # ========== IMAGE OPTIMIZATION MODULE ==========
    def on_size_preset_select(self, choice):
        """Handle size preset selection and update width/height fields"""
        if choice == "Mobile (480px)":
            self.width_var.set("480")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        elif choice == "Tablet (768px)":
            self.width_var.set("768")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        elif choice == "Desktop (1080px)":
            self.width_var.set("1080")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        elif choice == "Full HD (1920px)":
            self.width_var.set("1920")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        # Handle new 2K resolution
        elif choice == "2K (2560px)":
            self.width_var.set("2560")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        # Handle new 4K resolution
        elif choice == "4K (3840px)":
            self.width_var.set("3840")
            self.width_entry.configure(state="disabled")
            self.update_height_display()
        elif choice == "Custom...":
            self.width_var.set("")
            self.width_entry.configure(state="normal")
            self.height_var.set("")
        
    def update_height_display(self):
        """Calculate and display height based on current width and image aspect ratio"""
        if not self.images or self.current_image_index >= len(self.images):
            return
            
        try:
            # Get current image
            img_path = self.images[self.current_image_index]
            img = Image.open(img_path)
            
            # Get original dimensions
            orig_width, orig_height = img.size
            
            # Get selected width
            width_str = self.width_var.get()
            if not width_str:
                return
                
            width = int(width_str)
            
            # Calculate proportional height
            height = int((width / orig_width) * orig_height)
            self.height_var.set(str(height))
        except Exception as e:
            self.update_status_bar(f"Error calculating height: {str(e)}")
            
    def optimize_image(self, img, img_path):
        """Apply optimizations to image based on user settings"""
        # Apply EXIF orientation correction
        img = ImageOps.exif_transpose(img)
        
        # Apply other optimizations
        if self.strip_meta_var.get():
            img = self.strip_metadata(img)
            
        if self.comp_mode.get() == "lossy":
            quality = int(self.quality_slider.get())
            if self.format_var.get() == "jpeg":
                img = img.convert("RGB")
                
        return img
            
    def process_image(self, img_path):
        """Process a single image with all optimizations and resizing"""
        try:
            # Open the image
            img = Image.open(img_path)
            
            # Apply orientation and optimization
            img = self.optimize_image(img, img_path)
            
            # For processing, handle sizes
            optimized_versions = []
            sizes = []
            
            # Get custom sizes if specified
            custom_width = self.width_var.get().strip()
            custom_height = self.height_var.get().strip()
            
            if custom_width or custom_height:
                try:
                    width = int(custom_width) if custom_width else None
                    height = int(custom_height) if custom_height else None
                    sizes.append((width, height))
                except ValueError:
                    pass
            else:
                # Use preset sizes
                preset = self.size_presets.get()
                if preset == "Mobile (480px)":
                    sizes.append((480, None))
                elif preset == "Tablet (768px)":
                    sizes.append((768, None))
                elif preset == "Desktop (1080px)":
                    sizes.append((1080, None))
                elif preset == "Full HD (1920px)":
                    sizes.append((1920, None))
                # Handle new 2K resolution
                elif preset == "2K (2560px)":
                    sizes.append((2560, None))
                # Handle new 4K resolution
                elif preset == "4K (3840px)":
                    sizes.append((3840, None))
            
            # Process each size
            for size in sizes:
                width, height = size
                resized_img = self.resize_image(img.copy(), width, height)
                optimized_img = self.save_optimized(resized_img, img_path, width, height)
                optimized_versions.append(optimized_img)
                
                # Generate LQIP if requested
                if self.lqip_var.get():
                    lqip_img = self.generate_lqip(resized_img, img_path)
                    optimized_versions.append(lqip_img)
                    
            return optimized_versions
        except Exception as e:
            self.update_status_bar(f"Error processing {os.path.basename(img_path)}: {str(e)}")
            logging.error(f"Error processing {img_path}: {str(e)}")
            return []
        
    def resize_image(self, img, width=None, height=None):
        """Resize image while maintaining aspect ratio"""
        orig_width, orig_height = img.size
        
        # If both dimensions are specified
        if width and height:
            # Calculate the ratio to fit within the given dimensions
            ratio = min(width / orig_width, height / orig_height)
            new_width = int(orig_width * ratio)
            new_height = int(orig_height * ratio)
            new_size = (new_width, new_height)
        # If only width is specified
        elif width:
            ratio = width / orig_width
            new_height = int(orig_height * ratio)
            new_size = (width, new_height)
        # If only height is specified
        elif height:
            ratio = height / orig_height
            new_width = int(orig_width * ratio)
            new_size = (new_width, height)
        # No dimensions specified
        else:
            return img
            
        return img.resize(new_size, Image.LANCZOS)
        
    def strip_metadata(self, img):
        """Remove EXIF metadata from image"""
        # Create new image without metadata
        data = list(img.getdata())
        if img.mode == 'P':
            # Palette mode needs special handling
            stripped_img = Image.new(img.mode, img.size)
            stripped_img.putdata(data)
            stripped_img.putpalette(img.getpalette())
        else:
            stripped_img = Image.new(img.mode, img.size)
            stripped_img.putdata(data)
        return stripped_img
        
    def generate_lqip(self, img, img_path):
        """Create Low-Quality Image Placeholder (LQIP)"""
        # Create low-quality image placeholder
        lqip = img.copy()
        lqip.thumbnail((20, 20))
        lqip = lqip.filter(ImageFilter.GaussianBlur(radius=2))
        return self.save_optimized(lqip, img_path, suffix="_lqip")
        
    def save_optimized(self, img, img_path, width=None, height=None, suffix=""):
        """Save optimized image with appropriate settings"""
        # Determine output format
        output_format = self.format_var.get().upper()
        if output_format == "JPEG":
            img = img.convert("RGB")
            
        # Generate filename
        original_name = os.path.splitext(os.path.basename(img_path))[0]
        
        if self.hash_names_var.get():
            # Use hashed filenames if option is checked
            hash_str = hashlib.md5(img.tobytes()).hexdigest()[:8]
            file_name = f"{hash_str}{suffix}.{output_format.lower()}"
        else:
            # Keep original filename with size suffix
            size_info = ""
            if width or height:
                if width and height:
                    size_info = f"_{width}x{height}"
                elif width:
                    size_info = f"_{width}w"
                elif height:
                    size_info = f"_{height}h"
                    
            file_name = f"{original_name}.{output_format.lower()}" # {size_info}{suffix} Add size suffix
            
        output_path = os.path.join(self.output_dir, file_name)
        
        # Save options
        save_kwargs = {}
        if output_format == "JPEG":
            save_kwargs["quality"] = int(self.quality_slider.get())
            save_kwargs["progressive"] = self.progressive_var.get()
        elif output_format == "WEBP":
            save_kwargs["quality"] = int(self.quality_slider.get())
            save_kwargs["method"] = 6  # Higher compression
        elif output_format == "AVIF":
            save_kwargs["quality"] = int(self.quality_slider.get())
            
        img.save(output_path, format=output_format, **save_kwargs)
        
        return {
            "path": output_path,
            "size": os.path.getsize(output_path),
            "original_size": os.path.getsize(img_path),
            "dimensions": img.size
        }
        
    def start_processing(self):
        """Start image optimization process"""
        if not self.images:
            self.update_status_bar("No images to process")
            return
            
        # Reset processing state
        self.processing = True
        self.optimized_images = []
        
        self.output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not self.output_dir:
            self.processing = False
            return
            
        # Update status to processing
        self.update_status_bar("Processing", 0, len(self.images))
        
        # Start processing in a separate thread
        self.processing_thread = threading.Thread(target=self.process_images)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        
    def process_images(self):
        """Process all images in batch mode"""
        total = len(self.images)
        report_data = []
        
        for i, img_path in enumerate(self.images):
            if not self.processing:  # Allow cancellation
                break
                
            try:
                # Update progress
                self.update_status_bar("Processing", i+1, total)
                
                # Process image
                optimized = self.process_image(img_path)
                self.optimized_images.append(optimized)
                
                # Collect report data
                for version in optimized:
                    original_size = version["original_size"]
                    new_size = version["size"]
                    savings = original_size - new_size
                    ratio = (savings / original_size) * 100
                    
                    report_data.append({
                        "file": os.path.basename(version["path"]),
                        "original_size": self.format_size(original_size),
                        "new_size": self.format_size(new_size),
                        "savings": self.format_size(savings),
                        "ratio": f"{ratio:.1f}%",
                        "dimensions": version["dimensions"]
                    })
                    
            except Exception as e:
                self.update_status_bar(f"Error processing {os.path.basename(img_path)}")
                logging.error(f"Error processing {img_path}: {str(e)}")
                
        # Generate report if processing completed
        if self.processing:
            self.generate_report(report_data)
            self.update_status_bar("Done", total, total)
        
    # ========== COMMON METHODS ==========
    def setup_main_area(self):
        """Set up main content area with preview and file list"""
        # Preview area
        self.preview_frame = ctk.CTkFrame(
            self.main_frame, 
            fg_color="#3a3a3a",
            corner_radius=8
        )
        self.preview_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="nsew")
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_frame.grid_remove()  # Hidden initially
        
        # Preview title
        ctk.CTkLabel(
            self.preview_frame, 
            text="Optimized Preview", 
            font=("Arial", 14, "bold"),
            anchor="center"
        ).grid(row=0, column=0, pady=(5, 10), sticky="n")
        
        # Preview container
        self.preview_container = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.preview_container.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.preview_container.grid_columnconfigure(0, weight=1)
        self.preview_container.grid_rowconfigure(0, weight=1)
        
        # Image preview label
        self.preview_label = ctk.CTkLabel(
            self.preview_container, 
            text="",
            fg_color="transparent"
        )
        self.preview_label.pack(fill="both", expand=True, padx=10, pady=10)
        
        # File list section
        self.file_frame = ctk.CTkFrame(
            self.main_frame, 
            fg_color="#3a3a3a",
            corner_radius=8
        )
        self.file_frame.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="nsew")
        self.file_frame.grid_columnconfigure(0, weight=1)
        self.file_frame.grid_rowconfigure(0, weight=1)
        self.file_frame.grid_remove()  # Hidden initially
        
        # Section title
        ctk.CTkLabel(
            self.file_frame, 
            text="List of Files", 
            font=("Arial", 14, "bold")
        ).pack(pady=(5, 10))
        
        # Create Treeview for file metadata
        tree_container = ctk.CTkFrame(self.file_frame, fg_color="transparent")
        tree_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Define columns for metadata
        self.columns = (
            "filename", "author", "size", "file_type", "extension", 
            "date", "date_taken", "dimensions", "resolution", "camera"
        )
        
        # Create Treeview with dark mode styling
        style = ttk.Style()
        style.theme_use("default")
        
        # Configure Treeview colors for dark mode
        style.configure(
            "Treeview",
            background="#2a2a2a",
            foreground="white",
            fieldbackground="#2a2a2a",
            font=("Arial", 10),
            rowheight=25
        )
        
        # Configure Treeview header styling
        style.configure(
            "Treeview.Heading",
            background="#2b2b2b",  # Match dark theme
            foreground="white",
            relief="raised",  # Keep borders
            font=("Arial", 10, "bold")
        )
        
        # Hover effect for headers
        style.map(
            "Treeview.Heading",
            background=[("active", "#3a3a3a")]  # Light grey on hover
        )
        
        # Create Treeview
        self.tree = ttk.Treeview(
            tree_container,
            columns=self.columns,
            show="headings",
            selectmode="browse",
            style="Treeview"
        )
        
        # Define column headings
        self.tree.heading("filename", text="Filename")
        self.tree.heading("author", text="Author")
        self.tree.heading("size", text="File Size")
        self.tree.heading("file_type", text="File Type")
        self.tree.heading("extension", text="Extension")
        self.tree.heading("date", text="Date")
        self.tree.heading("date_taken", text="Date Taken")
        self.tree.heading("dimensions", text="Dimensions")
        self.tree.heading("resolution", text="Resolution")
        self.tree.heading("camera", text="Camera Model")
        
        # Set column widths
        self.tree.column("filename", width=120)
        self.tree.column("author", width=80)
        self.tree.column("size", width=80)
        self.tree.column("file_type", width=80)
        self.tree.column("extension", width=70)
        self.tree.column("date", width=100)
        self.tree.column("date_taken", width=100)
        self.tree.column("dimensions", width=80)
        self.tree.column("resolution", width=80)
        self.tree.column("camera", width=100)
        
        # Add scrollbars
        vsb = ttk.Scrollbar(
            tree_container, 
            orient="vertical", 
            command=self.tree.yview
        )
        hsb = ttk.Scrollbar(
            tree_container, 
            orient="horizontal", 
            command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Grid layout
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        # Configure grid weights
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)
        
        # Bind selection event
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
    def setup_status_bar(self):
        """Create status bar at bottom of main content area"""
        self.status_bar = ctk.CTkFrame(
            self.main_frame, 
            height=30,
            fg_color="#333333"
        )
        self.status_bar.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        # Configure grid
        self.status_bar.grid_columnconfigure(0, weight=0)
        self.status_bar.grid_columnconfigure(1, weight=1)
        self.status_bar.grid_columnconfigure(2, weight=0)
        
        # Status message
        self.status_label = ctk.CTkLabel(
            self.status_bar, 
            text="Ready | Files: 0",
            font=("Arial", 10)
        )
        self.status_label.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        
        # Progress bar
        self.progress = ctk.CTkProgressBar(
            self.status_bar, 
            mode="determinate",
            progress_color="#FFA500"  # Start with orange
        )
        self.progress.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.progress.set(0)
        
        # Processing info
        self.progress_info = ctk.CTkLabel(
            self.status_bar, 
            text="0/0",
            font=("Arial", 10)
        )
        self.progress_info.grid(row=0, column=2, padx=(5, 10), pady=5, sticky="e")
        
    def update_status_bar(self, status="Ready", current=0, total=0):
        """
        Update status bar with current status and progress
        - Ready: Orange
        - Processing: Red
        - Done: Green
        """
        self.status_label.configure(text=f"{status} | Files: {len(self.images)}")
        
        if total > 0:
            percent = (current / total) * 100
            self.progress_info.configure(text=f"{current}/{total} ({percent:.1f}%)")
        else:
            self.progress_info.configure(text="")
        
        # Update progress bar color based on state
        if status == "Ready":
            self.progress.configure(progress_color="#FFA500")
        elif status == "Processing":
            self.progress.configure(progress_color="#FF0000")
        elif status == "Done":
            self.progress.configure(progress_color="#00FF00")
            
        # Set progress value
        if total > 0:
            self.progress.set(current / total)
        else:
            self.progress.set(0)
        
    def update_quality_label(self, value):
        """Update quality slider label"""
        self.quality_label.configure(text=f"Quality: {int(float(value))}%")
            
    def extract_metadata(self, file_path):
        """
        Extract comprehensive metadata from file
        - For image files: Author, File Size, File Type, Extension
          Date, Date Taken, Dimensions, Resolution, Camera Model
        - For non-image files: Basic file info only
        """
        try:
            # Get basic file info that applies to all file types
            file_size = os.path.getsize(file_path)
            file_ext = os.path.splitext(file_path)[1][1:].upper()
            mod_date = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M")
            
            # Initialize with default values for non-image files
            author = "N/A"
            date_taken = "N/A"
            dimensions = "N/A"
            resolution = "N/A"
            camera_model = "N/A"
            file_type = "Other"
            
            # Only extract image-specific metadata for image files
            if self.is_image_file(file_path):
                file_type = "Image"
                img = Image.open(file_path)
                exif_data = img.getexif() if hasattr(img, 'getexif') else {}
                
                # Get dimensions for images
                dimensions = f"{img.width}×{img.height}"
                
                # Get resolution for images
                dpi = img.info.get('dpi', (0, 0))
                resolution = f"{dpi[0]}×{dpi[1]} DPI" if dpi[0] > 0 else "N/A"
                
                # Extract EXIF data for images
                if exif_data:
                    # Helper function to get EXIF tag
                    def get_exif_tag(tag_id):
                        return exif_data.get(tag_id, "")
                    
                    # Get author
                    author = get_exif_tag(315) or ""
                    
                    # Get date taken
                    date_taken = get_exif_tag(36867) or ""
                    
                    # Get camera model
                    camera_model = get_exif_tag(272) or ""
            
            return {
                "filename": os.path.basename(file_path),
                "author": author,
                "size": self.format_size(file_size),
                "file_type": file_type,
                "extension": file_ext,
                "date": mod_date,
                "date_taken": date_taken,
                "dimensions": dimensions,
                "resolution": resolution,
                "camera": camera_model
            }
            
        except Exception as e:
            logging.error(f"Error extracting metadata: {str(e)}")
            return {
                "filename": os.path.basename(file_path),
                "author": "N/A",
                "size": "N/A",
                "file_type": "N/A",
                "extension": "N/A",
                "date": "N/A",
                "date_taken": "N/A",
                "dimensions": "N/A",
                "resolution": "N/A",
                "camera": "N/A"
            }
    
    def is_image_file(self, file_path):
        """Check if a file is an image based on its extension"""
        image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp')
        return os.path.splitext(file_path)[1].lower() in image_extensions
    
    def update_file_list(self):
        """Populate treeview with file metadata"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add new items
        for meta in self.image_metadata:
            self.tree.insert("", "end", values=(
                meta["filename"],
                meta["author"],
                meta["size"],
                meta["file_type"],
                meta["extension"],
                meta["date"],
                meta["date_taken"],
                meta["dimensions"],
                meta["resolution"],
                meta["camera"]
            ))
        
        # Select first item if available
        if self.image_metadata:
            first_item = self.tree.get_children()[0]
            self.tree.selection_set(first_item)
            self.tree.focus(first_item)
            
    def on_tree_select(self, event):
        """Handle file selection from treeview - update preview if image"""
        selected = self.tree.selection()
        if selected:
            index = self.tree.index(selected[0])
            if 0 <= index < len(self.images):
                self.current_image_index = index
                
                # Only show preview for image files in optimize mode
                if (self.mode_var.get() == "optimize" and 
                    self.is_image_file(self.images[self.current_image_index])):
                    self.show_image()
                    self.update_height_display()
                
    def show_work_area(self):
        """Show preview and file list when files are loaded"""
        # Always show file list
        self.file_frame.grid()
        
        # Only show preview in optimization mode for images
        if self.mode_var.get() == "optimize" and self.images:
            self.preview_frame.grid()
        
        self.status_bar.grid()
        
    def show_image(self):
        """Display the selected image in the preview area (only for image files)"""
        if not self.images or self.current_image_index >= len(self.images):
            return
            
        img_path = self.images[self.current_image_index]
        if not self.is_image_file(img_path):
            return
            
        try:
            # Open and apply orientation correction
            img = Image.open(img_path)
            img = ImageOps.exif_transpose(img)  # Fix orientation
            
            # Resize for preview
            img.thumbnail((600, 600))
            
            # Create CTkImage and display
            img_tk = ctk.CTkImage(light_image=img, size=img.size)
            self.preview_label.configure(image=img_tk, text="")
            
        except Exception as e:
            self.update_status_bar(f"Error: {str(e)}")
            
    def format_size(self, size):
        """Convert bytes to human-readable format"""
        if size == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB")
        i = int(math.floor(math.log(size, 1024)))
        p = math.pow(1024, i)
        s = round(size / p, 2)
        return f"{s} {size_name[i]}"
        
    def generate_report(self, data):
        """Generate optimization reports in JSON and HTML formats"""
        report_path = os.path.join(self.output_dir, "optimization_report.json")
        with open(report_path, "w") as f:
            json.dump(data, f, indent=2)
            
        # Generate HTML report
        html_path = os.path.join(self.output_dir, "report.html")
        with open(html_path, "w") as f:
            f.write("<html><head><style>")
            f.write("body { font-family: Arial, sans-serif; }")
            f.write("table { border-collapse: collapse; width: 100%; }")
            f.write("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
            f.write("tr:nth-child(even) { background-color: #f2f2f2; }")
            f.write("th { background-color: #4CAF50; color: white; }")
            f.write("</style></head><body>")
            f.write("<h1>Image Optimization Report</h1>")
            f.write("<table>")
            f.write("<tr>")
            f.write("<th>File</th><th>Original</th><th>Optimized</th><th>Savings</th><th>Ratio</th><th>Dimensions</th>")
            f.write("</tr>")
            
            for item in data:
                f.write("<tr>")
                f.write(f"<td>{item['file']}</td>")
                f.write(f"<td>{item['original_size']}</td>")
                f.write(f"<td>{item['new_size']}</td>")
                f.write(f"<td>{item['savings']}</td>")
                f.write(f"<td>{item['ratio']}</td>")
                f.write(f"<td>{item['dimensions'][0]}x{item['dimensions'][1]}</td>")
                f.write("</tr>")
                
            f.write("</table></body></html>")
    
    def reset_application(self):
        """Reset the application to initial state"""
        # Clear all data
        self.images = []
        self.image_metadata = []
        self.optimized_images = []
        self.current_image_index = 0
        self.output_dir = ""
        self.processing = False
        
        # Reset UI elements - clear Treeview explicitly
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.preview_label.configure(image=None, text="")
        self.update_status_bar("Ready")
        
        # Hide the preview and file list sections
        self.preview_frame.grid_remove()
        self.file_frame.grid_remove()
        
        # Reset settings to defaults
        self.format_var.set("webp")
        self.comp_mode.set("lossless")  # Set back to lossless
        self.quality_slider.set(100)
        self.quality_label.configure(text="Quality: 100%")
        self.size_presets.set("Full HD (1920px)")
        self.width_var.set("1920")
        self.height_var.set("")
        self.width_entry.configure(state="disabled")
        self.progressive_var.set(True)
        self.lqip_var.set(False)
        self.strip_meta_var.set(False)
        self.hash_names_var.set(False)  # Default to unchecked
        
        # Reset renaming controls
        self.rename_format_var.set("sequential")
        self.prefix_var.set("")
        self.suffix_var.set("")
        self.include_date_var.set(True)
        self.include_time_var.set(True)
        
        # Set back to optimization mode
        self.toggle_mode("optimize")

if __name__ == "__main__":
    try:
        app = ImageOptimizerApp()
        app.mainloop()
    except Exception as e:
        logging.exception("Critical error occurred")
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror(
                "Fatal Error",
                f"Application crashed: {str(e)}\nCheck image_optimizer.log for details"
            )
        except:
            pass